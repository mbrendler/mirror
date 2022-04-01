#!/usr/bin/env python3

import sys
import os
from shlex import quote
from subprocess import getoutput
from argparse import ArgumentParser
from pprint import pprint
import json
from urllib.request import urlopen, Request
from urllib.error import HTTPError
from getpass import getpass
import importlib.util
from functools import cache
from multiprocessing import Pool


COLOR = False
TPUT_REPO = ''
TPUT_OP = ''


if sys.stdout.isatty():
    COLOR = True
    TPUT_REPO = getoutput('tput setaf 3')
    TPUT_OP = getoutput('tput op')


@cache
def dotfile():
    try:
        dotfile_path = os.path.join(os.getenv('HOME'), '.mirror.py')
        spec = importlib.util.spec_from_file_location("dotfile", dotfile_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except FileNotFoundError:
        return None


@cache
def github_authorization():
    if dotfile():
        return dotfile().github_authorization()
    return 'token ' + getpass('github token: ')


def base_dir(options):
    return os.path.join(options.path, options.name)


def parse_options():
    parser = ArgumentParser(description='Queries Github API')
    parser.add_argument(
        'name', metavar='USER_OR_ORG', nargs='?',
        help='User- or Organization name'
    )
    parser.add_argument(
        '--archived', dest='include_archived', action='store_true',
        default=False, help='inclue archived repositories'
    )
    parser.add_argument(
        '-p', '--path', dest='path', metavar='PATH',
        default=f"{os.environ['HOME']}/tmp/repos", help='repository path'
    )
    parser.set_defaults(func=cmd_help)

    subparsers = parser.add_subparsers()

    list_parser = subparsers.add_parser('list', help=cmd_list.__doc__)
    list_parser.set_defaults(func=cmd_list)
    list_parser.add_argument(
        '-f', '--format', dest='format', metavar='FORMAT',
        default='%(clone_url)s', help='output format of repository'
    )
    list_parser.add_argument(
        '--raw', dest='raw', action='store_true', default=False,
        help='show raw repo values'
    )
    list_parser.add_argument(
        'repo', metavar='REPO', nargs='?', help='Repository name'
    )

    fetch_parser = subparsers.add_parser('fetch', help=cmd_fetch.__doc__)
    fetch_parser.set_defaults(func=cmd_fetch)

    abandon_parser = subparsers.add_parser('abandon', help=cmd_abandon.__doc__)
    abandon_parser.set_defaults(func=cmd_abandon)

    grep_parser = subparsers.add_parser('grep', help=cmd_grep.__doc__)
    grep_parser.set_defaults(func=cmd_grep)
    grep_parser.add_argument(
        '--ref', dest='ref', metavar='REF', default='HEAD', help='Git ref'
    )
    grep_parser.add_argument(
        'pattern', metavar='PATTERN', help='Grep pattern'
    )
    grep_parser.add_argument(
        'files', metavar='FILE', nargs='*', help='files'
    )

    return parser.parse_args()


def cmd_help(options):
    sys.argv.insert(1, '--help')
    parse_options()


def cmd_list(options):
    "list all repositories"
    repos = find_repos(options)
    for repo in repos:
        if options.raw:
            print(repo.name)
            pprint(repo.raw_data)
        else:
            print(options.format % repo.raw_data)


def fetch_repo_worker(repo):
    directory = os.path.basename(repo.clone_url)
    print(TPUT_REPO + directory + TPUT_OP)
    if os.path.exists(directory):
        os.system(f'git -C {directory} fetch --all --prune')
    else:
        os.system(f'git clone --mirror {repo.clone_url}')

def main_branch_name(repo_path):
    repo_path = quote(repo_path)
    branches = getoutput(f"git --no-pager -C '{repo_path}' branch --list")
    branches = branches.splitlines(False)
    if "  main" in branches:
        return 'main'
    if "  master" in branches:
        return 'master'
    return 'HEAD'

def cmd_fetch(options):
    "fetch all repositories"
    repos = find_repos(options)
    current_dir = os.path.join(base_dir(options), 'current')
    os.makedirs(current_dir, exist_ok=True)
    os.chdir(current_dir)
    with Pool(20) as p:
        p.map(fetch_repo_worker, repos)
    cmd_abandon(options, repos=repos)


def cmd_abandon(options, repos=None):
    "abandon archived or deleted repositories"
    if repos is None:
        repos = find_repos(options)
    repo_dirs = [os.path.basename(repo.clone_url) for repo in repos]
    current_dir = os.path.join(base_dir(options), 'current')
    abandoned_dir = os.path.join(base_dir(options), 'abandoned')
    os.makedirs(abandoned_dir, exist_ok=True)
    for directory in os.listdir(current_dir):
        if directory not in repo_dirs:
            os.rename(
                os.path.join(current_dir, directory),
                os.path.join(abandoned_dir, directory)
            )
            print(directory + ' abandoned')


def git_grep(directory, repo_path, pattern, ref, files):
    color = '--color=always' if COLOR else ''
    repo_path = quote(repo_path)
    files = ' '.join(files)
    os.system(
        f'git --no-pager -C "{repo_path}" grep -E {pattern} {ref} -- {files}'
        f' | sed -E "s/^/{TPUT_REPO}{directory}{TPUT_OP}:/"'
    )

def cmd_grep(options):
    "grep in all repositories"
    current_dir = os.path.join(base_dir(options), 'current')
    for directory in os.listdir(current_dir):
        repo_path = os.path.join(current_dir, directory)
        branch = main_branch_name(repo_path)
        git_grep(directory, repo_path, options.pattern, branch, options.files)


def http_get(url):
    request = Request(url)
    request.add_header('Authorization', github_authorization())
    request.add_header('User-Agent', 'curl')
    response = urlopen(request)
    if response.status == 200:
        return response.read()
    return None


def github_user():
    response_body = http_get('https://api.github.com/user')
    return json.loads(response_body)


def find_repos(options):
    user_or_org = options.name or github_user()['login']
    if hasattr(options, 'repo') and options.repo:
        return [Repo.find(user_or_org, options.repo)]
    else:
        repos = Repo.all_for(user_or_org)
        if not options.include_archived:
            repos = [repo for repo in repos if not repo.archived]
        return repos


class Repo:
    @classmethod
    def all_for(cls, org_or_user):
        try:
            return cls.for_org(org_or_user)
        except HTTPError as e:
            if e.status == 404:
                return cls.for_user(org_or_user)
            raise e

    @classmethod
    def for_org(cls, org):
        url = f'https://api.github.com/orgs/{org}/repos'
        return cls.from_url(url)

    @classmethod
    def for_user(cls, user):
        url = f'https://api.github.com/users/{user}/repos'
        return cls.from_url(url)

    @classmethod
    def find(cls, org_or_user, name):
        url = f'https://api.github.com/repos/{org_or_user}/{name}'
        return cls.from_url(url)

    @classmethod
    def from_url(cls, url, page=1):
        response_body = http_get(f'{url}?per_page=100&page={page}')
        if response_body is None:
            return None
        raws = json.loads(response_body)
        if isinstance(raws, list):
            result = [cls(raw) for raw in raws]
            if len(raws) == 100:
                result.extend(cls.from_url(url, page + 1) or [])
            return result
        return cls(raws)

    def __init__(self, raw):
        self.raw_data = raw

    def __repr__(self):
        return repr(self.raw_data)

    def __getstate__(self):
       return self.__dict__

    def __setstate__(self, d):
       self.__dict__ = d

    def __getattr__(self, name):
        return self.raw_data[name]


def main():
    options = parse_options()
    options.func(options)


if __name__ == '__main__' and not sys.flags.interactive:
    main()
