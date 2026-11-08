# Security

- Generated-code execution remains BLOCKED.
- Downloads reject private/localhost targets.
- Draft apply requires fingerprint-bound approval.
- Sensitive files are rejected before write: `.env*`, known private keys, `kubeconfig`, `.kube/config`, and known credential filenames.
- Ordinary names such as `secret_notes.py`, `app.key`, and `id_rsa.pub` are not blocked.
- Symlink rejection is a time-of-check check only. Race protection is not claimed.
- Desktop automation requires permission and approval. Real drivers are not verified. Termux fails closed.
- Desktop audit logs do not store secret payloads.
- Desktop and plugin actions require approval.
- Freelancer external actions require approval.
- Secrets stay in environment variables.
