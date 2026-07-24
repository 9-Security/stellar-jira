# GitHub push（一次性）

Repo: https://github.com/9-Security/stellar-jira

## 1. 加入 Deploy key（只需做一次）

GitHub → **Settings → Deploy keys → Add deploy key**

- Title: `stellar-jira-vm-deploy`
- Key: 貼上 [`github_deploy_key.pub`](github_deploy_key.pub) 內容
- ✅ Allow write access（若要從 VM push）

## 2. 從本機 push

```bash
cd /opt/stellar-jira
export GIT_SSH_COMMAND='ssh -i ~/.ssh/id_ed25519_9security_stellar -o IdentitiesOnly=yes'
git remote add origin git@github.com:9-Security/stellar-jira.git 2>/dev/null || true
git push -u origin main
```

私鑰路徑：`~/.ssh/id_ed25519_9security_stellar`（僅存於此 VM，勿提交 Git）。
