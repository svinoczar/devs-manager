from enum import Enum


class VCS(str, Enum):
    github = "github"
    gitlab = "gitlab"
    bitbucket = "bitbucket"
    svn = "svn"
