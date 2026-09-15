# Maintainer release checklist

## Before changing repository visibility

1. Confirm that all contributors have permission to publish their work and
   that MIT is the intended license.
2. Run CI on the exact commit being published. Review secret-scan results for
   the full Git history, not just the current tree.
3. Check tracked files and historical paths for environment files, deployment
   state, database dumps, internal links and real customer data. Never publish
   `.local/` or `.azure/`. Rotate exposed credentials before considering a
   history rewrite.
4. Review dependency notices, especially when publishing container images.
   Publishing the source does not automatically license upstream model data.
5. Change visibility deliberately in GitHub settings. This is separate from
   deploying the dashboard, and preparation scripts never change visibility.
6. Once public, enable private vulnerability reporting and GitHub's available
   secret-scanning/push-protection features. Check that the private reporting
   link in `SECURITY.md` works. Do not enable paid features without approval.

## Ongoing maintenance

CI runs on pushes and pull requests with read-only repository permissions.
It uses full-SHA action references, synthetic catalogue data and no Azure
credentials. Fork pull requests must not receive deployment secrets. Do not
switch the workflow to `pull_request_target` to run untrusted contributor code.

Review Dependabot updates and CI results before merging. Consider requiring
the `checks` job on `main` once the first workflow run succeeds. Do not claim
support for untested platforms or guarantee vulnerability response times.

Azure deployment remains an explicit operator action. CI does not provision
cloud resources, update the public dashboard or change its database.
