# Security reports

Do not put exploit details, pairing codes, session cookies, personal audio, or private logs in public issues.

When private vulnerability reporting is enabled, use **Security → Advisories → Report a vulnerability** on [TuxCue's repository](https://github.com/TuxCue/TuxCue/security/advisories). If that option is unavailable, open an issue containing only a request for a private reporting channel; wait for a private route before sharing details. No private email address is published here.

Include the TuxCue version, package/source installation, distribution, affected feature, and concise reproduction steps. The project aims to assess reports and release fixes, but does not promise a response deadline. Only the latest public 0.x release is intended to receive fixes.

## Trust boundaries

The desktop interface binds to loopback and trusts local processes. Optional phone control binds a separate port, permits private IPv4 peers, and requires pairing for controls. Phone traffic uses HTTP and is not encrypted; use a trusted network and do not port-forward the listener. Disable Remote control or forget a phone to revoke access.

Imported media is processed by FFmpeg with the user's permissions. Keep TuxCue and system media packages updated. AppImages bundle their own media dependencies, so updating the operating system alone does not update those copies.
