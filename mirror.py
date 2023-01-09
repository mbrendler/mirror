#!/usr/bin/env python3

import importlib.util
import json
import os
import sys
from argparse import ArgumentParser
from functools import cache
from getpass import getpass
from multiprocessing import Pool
from pprint import pprint
from shlex import quote
from subprocess import getoutput
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

COLOR = False
TPUT_REPO = ""
TPUT_OP = ""


if sys.stdout.isatty():
    COLOR = True
    TPUT_REPO = getoutput("tput setaf 3")
    TPUT_OP = getoutput("tput op")


@cache
def dotfile() -> Any:
    try:
        dotfile_path = os.path.join(os.environ["HOME"], ".mirror.py")
        spec = importlib.util.spec_from_file_location("dotfile", dotfile_path)
        module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        return module
    except FileNotFoundError:
        return None


@cache
def github_authorization() -> str:
    if dotfile():
        return dotfile().github_authorization()  # type: ignore[no-any-return]
    return "token " + getpass("github token: ")


def base_dir(options: Any) -> str:
    return f"{options.path}/{options.name}"


def parse_options() -> Any:
    parser = ArgumentParser(description="Queries Github API")
    parser.add_argument(
        "name",
        metavar="USER_OR_ORG",
        nargs="?",
        help="User- or Organization name",
    )
    parser.add_argument(
        "--archived",
        dest="include_archived",
        action="store_true",
        default=False,
        help="include archived repositories",
    )
    parser.add_argument(
        "-p",
        "--path",
        dest="path",
        metavar="PATH",
        default=f"{os.environ['HOME']}/tmp/repos",  # noqa: S108
        help="repository path",
    )
    parser.set_defaults(func=cmd_help)

    subparsers = parser.add_subparsers()

    list_parser = subparsers.add_parser("list", help=cmd_list.__doc__)
    list_parser.set_defaults(func=cmd_list)
    list_parser.add_argument(
        "-f",
        "--format",
        dest="format",
        metavar="FORMAT",
        default="%(clone_url)s",
        help="output format of repository",
    )
    list_parser.add_argument(
        "--raw",
        dest="raw",
        action="store_true",
        default=False,
        help="show raw repo values",
    )
    list_parser.add_argument(
        "repo", metavar="REPO", nargs="?", help="Repository name"
    )

    fetch_parser = subparsers.add_parser("fetch", help=cmd_fetch.__doc__)
    fetch_parser.set_defaults(func=cmd_fetch)

    abandon_parser = subparsers.add_parser("abandon", help=cmd_abandon.__doc__)
    abandon_parser.set_defaults(func=cmd_abandon)

    grep_parser = subparsers.add_parser("grep", help=cmd_grep.__doc__)
    grep_parser.set_defaults(func=cmd_grep)
    grep_parser.add_argument(
        "--ref", dest="ref", metavar="REF", default="HEAD", help="Git ref"
    )
    grep_parser.add_argument("pattern", metavar="PATTERN", help="Grep pattern")
    grep_parser.add_argument("files", metavar="FILE", nargs="*", help="files")

    ls_files_parser = subparsers.add_parser(
        "ls-files", help=cmd_ls_files.__doc__
    )
    ls_files_parser.set_defaults(func=cmd_ls_files)
    ls_files_parser.add_argument(
        "files", metavar="FILE", nargs="*", help="files"
    )

    return parser.parse_args()


def cmd_help(_options: Any) -> None:
    sys.argv.insert(1, "--help")
    parse_options()


def cmd_list(options: Any) -> None:
    """list all repositories"""
    repos = find_repos(options)
    for repo in repos:
        if options.raw:
            print(repo.name)
            pprint(repo.raw_data)
        else:
            print(options.format % repo.raw_data)


def fetch_repo_worker(repo: "Repo") -> Any:
    directory = os.path.basename(repo.clone_url)
    print(TPUT_REPO + directory + TPUT_OP)
    if os.path.exists(directory):
        os.system(f"git -C {directory} fetch --all --prune")
    else:
        os.system(f"git clone --mirror {repo.clone_url}")


def main_branch_name(repo_path: str) -> str:
    repo_path = quote(repo_path)
    branches_str = getoutput(f"git --no-pager -C '{repo_path}' branch --list")
    branches = branches_str.splitlines(keepends=False)
    if "  main" in branches:
        return "main"
    if "  master" in branches:
        return "master"
    return "HEAD"


def cmd_fetch(options: Any) -> None:
    """fetch all repositories"""
    repos = find_repos(options)
    current_dir = os.path.join(base_dir(options), "current")
    os.makedirs(current_dir, exist_ok=True)
    os.chdir(current_dir)
    with Pool(20) as pool:
        pool.map(fetch_repo_worker, repos)
    cmd_abandon(options, repos=repos)


def cmd_abandon(options: Any, repos: list["Repo"] | None = None) -> None:
    """abandon archived or deleted repositories"""
    if repos is None:
        repos = find_repos(options)
    repo_dirs = [os.path.basename(repo.clone_url) for repo in repos]
    current_dir = os.path.join(base_dir(options), "current")
    abandoned_dir = os.path.join(base_dir(options), "abandoned")
    os.makedirs(abandoned_dir, exist_ok=True)
    for directory in os.listdir(current_dir):
        if directory not in repo_dirs:
            os.rename(
                os.path.join(current_dir, directory),
                os.path.join(abandoned_dir, directory),
            )
            print(directory + " abandoned")


def git_grep(
    directory: str, repo_path: str, pattern: str, ref: str, file_list: list[str]
) -> None:
    color = "--color=always" if COLOR else ""
    repo_path = quote(repo_path)
    files = " ".join(file_list)
    os.system(
        f'git -C "{repo_path}" grep {color} -E {pattern} {ref} -- {files}'
        f' | sed -E "s/^/{TPUT_REPO}{directory}{TPUT_OP}:/"'
    )


def cmd_grep(options: Any) -> None:
    """grep in all repositories"""
    current_dir = os.path.join(base_dir(options), "current")
    for directory in os.listdir(current_dir):
        repo_path = os.path.join(current_dir, directory)
        branch = main_branch_name(repo_path)
        git_grep(directory, repo_path, options.pattern, branch, options.files)


def ls_files(
    directory: str, repo_path: str, ref: str, file_list: list[str]
) -> None:
    repo_path = quote(repo_path)
    files = " ".join(file_list)
    os.system(
        f'git -C "{repo_path}" ls-tree --full-tree -r --name-only {ref} {files}'
        f' | sed -E "s/^/{TPUT_REPO}{directory}{TPUT_OP}:/"'
    )


def cmd_ls_files(options: Any) -> None:
    """find files in all repositories"""
    current_dir = os.path.join(base_dir(options), "current")
    for directory in os.listdir(current_dir):
        repo_path = os.path.join(current_dir, directory)
        branch = main_branch_name(repo_path)
        ls_files(directory, repo_path, branch, options.files)


def http_get_json(url: str) -> Any:
    request = Request(url)
    request.add_header("Authorization", github_authorization())
    request.add_header("User-Agent", "curl")
    with urlopen(request) as response:
        status = response.status
        if status == 200:
            body = response.read()
            if body is not None:
                return json.loads(body)
        raise RuntimeError(f"Nothing found for {url=!r}, {status=}")


def github_user() -> dict[str, Any]:
    url = "https://api.github.com/user"
    return http_get_json(url)  # type: ignore[no-any-return]


def find_repos(options: Any) -> list["Repo"]:
    user_or_org = options.name or github_user()["login"]
    if hasattr(options, "repo") and options.repo:
        return [Repo.find(user_or_org, options.repo)]

    repos = Repo.all_for(user_or_org)
    if options.include_archived:
        return repos

    return [repo for repo in repos if not repo.archived]


class Repo:
    @classmethod
    def all_for(cls, org_or_user: str) -> list["Repo"]:
        try:
            return cls.for_org(org_or_user)
        except HTTPError as exc:
            if exc.status == 404:
                return cls.for_user(org_or_user)
            raise exc

    @classmethod
    def for_org(cls, org: str) -> list["Repo"]:
        url = f"https://api.github.com/orgs/{org}/repos"
        return cls.from_url(url)

    @classmethod
    def for_user(cls, user: str) -> list["Repo"]:
        url = f"https://api.github.com/users/{user}/repos"
        return cls.from_url(url)

    @classmethod
    def find(cls, org_or_user: str, name: str) -> "Repo":
        url = f"https://api.github.com/repos/{org_or_user}/{name}"
        raw = http_get_json(url)
        return cls(raw)

    @classmethod
    def from_url(cls, url: str, page: int = 1) -> list["Repo"]:
        raws = http_get_json(f"{url}?per_page=100&page={page}")
        result = [cls(raw) for raw in raws]
        if len(raws) == 100:
            result.extend(cls.from_url(url, page + 1) or [])
        return result

    def __init__(self, raw: dict[str, Any]) -> None:
        self.raw_data = raw

    def __repr__(self) -> str:
        return repr(self.raw_data)

    def __getstate__(self) -> dict[str, Any]:
        return self.__dict__

    def __setstate__(self, state: dict[str, Any]) -> None:
        self.__dict__ = state

    def __getattr__(self, name: str) -> Any:
        return self.raw_data[name]


def main() -> None:
    options = parse_options()
    options.func(options)


if __name__ == "__main__" and not sys.flags.interactive:
    main()
