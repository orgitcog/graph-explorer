# God Mode - Rapid Azure AD & GitHub Enterprise Bulk Provisioning

**Deploy entire organizational structures in seconds.**

God Mode provides ultra-fast bulk provisioning capabilities for Azure AD and GitHub Enterprise, similar to how GitHub Enterprise allows rapid org and repo creation.

## Features

- **Bulk User Creation** - Create hundreds of users in seconds
- **Organization/Group Provisioning** - Set up multiple departments/teams at once
- **Application Registration** - Batch create Azure AD applications
- **GitHub Integration** - Create orgs and repos alongside Azure resources
- **YAML Configuration** - Define infrastructure as code
- **Concurrent Execution** - Parallel API calls for maximum speed

## Quick Start

### Python CLI

```bash
# Check status
python god_mode.py status

# Provision 3 orgs with 50 users each (150 users total)
python god_mode.py provision --orgs 3 --users 50

# Provision from YAML config
python god_mode.py provision --config templates/infrastructure.yaml

# Include GitHub resources
python god_mode.py provision --orgs 3 --users 50 --github

# Generate sample config
python god_mode.py generate-config --output my-infra.yaml
```

### PowerShell Module

```powershell
# Import the module
Import-Module ./powershell/GodMode.psm1

# Check status
Get-GodModeStatus

# Provision infrastructure
New-GodModeInfrastructure -Organizations 3 -UsersPerOrg 50

# Provision from config file
New-GodModeInfrastructure -ConfigFile infrastructure.json
```

## Configuration

### Environment Variables

```bash
# Azure AD (Required)
export AZURE_TENANT_ID="your-tenant-id"
export AZURE_CLIENT_ID="your-client-id"
export AZURE_CLIENT_SECRET="your-client-secret"

# GitHub (Optional)
export GHE_ADMIN_TOKEN="your-github-pat"
# or
export beast="your-github-pat"
```

### Infrastructure YAML

```yaml
groups:
  - displayName: "Engineering"
    description: "Engineering department"
    securityEnabled: true

users:
  - displayName: "John Doe"
    username: "johndoe"
    department: "Engineering"
    jobTitle: "Developer"

github_repos:
  - org: "myorg"
    name: "my-repo"
    private: false
```

## Performance

| Operation | Count | Time |
|-----------|-------|------|
| Create Users | 100 | ~15 seconds |
| Create Groups | 10 | ~3 seconds |
| Create Repos | 10 | ~5 seconds |

*Performance depends on API rate limits and network latency.*

## Required Permissions

### Azure AD Application

The Azure AD application needs these Microsoft Graph permissions:

| Permission | Type | Description |
|------------|------|-------------|
| User.ReadWrite.All | Application | Create and manage users |
| Group.ReadWrite.All | Application | Create and manage groups |
| Application.ReadWrite.All | Application | Create and manage apps |
| Directory.ReadWrite.All | Application | Full directory access |

### GitHub

For GitHub Enterprise operations, you need a Personal Access Token with:
- `admin:org` - Organization management
- `repo` - Repository access
- `delete_repo` - Repository deletion (if needed)

## Examples

### Create a Complete Department

```bash
python god_mode.py provision --config - <<EOF
groups:
  - displayName: "New Department"
    description: "A new department"
    securityEnabled: true

users:
  - displayName: "Manager One"
    username: "manager1"
    department: "New Department"
    jobTitle: "Department Manager"
  - displayName: "Employee One"
    username: "employee1"
    department: "New Department"
    jobTitle: "Team Member"
EOF
```

### Rapid Multi-Tenant Setup

```bash
# Create 3 organizational units with 50 users each
python god_mode.py provision --orgs 3 --users 50

# This creates:
# - 3 security groups (Organization-01, Organization-02, Organization-03)
# - 150 users distributed across the organizations
# - All in under 30 seconds
```

### Sync with GitHub

```bash
# Provision Azure AD and GitHub together
python god_mode.py provision --orgs 3 --users 10 --github

# This also creates GitHub repos for each organization
```

## Output

Results are saved to `~/.godmode/provision_YYYYMMDD_HHMMSS.json`:

```json
{
  "groups": [
    {
      "success": true,
      "resource_type": "group",
      "resource_id": "abc123",
      "resource_name": "Organization-01"
    }
  ],
  "users": [
    {
      "success": true,
      "resource_type": "user",
      "resource_id": "def456",
      "resource_name": "User 001",
      "details": {
        "userPrincipalName": "user001@tenant.onmicrosoft.com",
        "tempPassword": "RandomP@ss123"
      }
    }
  ]
}
```

## Error Handling

God Mode continues provisioning even if individual operations fail. All errors are logged and reported in the summary:

```
Provisioning Complete!
Duration: 25.43 seconds

Summary:
  Groups created: 3
  Users created:  148
  Errors:         2

Errors:
  ✗ [User] User 049: User already exists
  ✗ [User] User 050: Invalid username format
```

## Integration with Graph Explorer

God Mode is designed to work alongside the Graph Explorer web interface:

1. Use **Graph Explorer** to explore and test individual API calls
2. Use **God Mode** to execute bulk operations at scale
3. Use the **Code Generator** to convert Graph Explorer queries to God Mode scripts

## License

Apache License 2.0
