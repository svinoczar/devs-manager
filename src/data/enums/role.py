from enum import Enum

class Role(Enum):
    ORGANIZATION_MANAGER = "Organization Manager" # 4
    PROJECT_MANAGER = "Project Manager" # 3
    TEAM_MANAGER = "Team Manager" # 2
    MEMBER = "Member" # 1
    NONE = "None" #0