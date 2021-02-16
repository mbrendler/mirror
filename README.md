# Mirror - mirrors github repositories

```
./mirror.py --help
```

## Dotfile - ~/.mirror.py

- load github access token from `pass` command:

```python
from subprocess import getoutput


def github_authorization():
    return 'token ' + getoutput('pass show github.com/access-token')
```
