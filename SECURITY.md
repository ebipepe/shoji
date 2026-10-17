# Security

Shoji filters HTTPS traffic on your own machine. That makes it powerful, and it means you should
understand what it does before you install it.

## What Shoji does with your traffic

- On first run Shoji generates a **root certificate authority (CA) that is unique to your PC**
  (`data/certs/`, shown in Windows as *"Shoji Local Filtering CA (this PC only)"*) and adds it to the
  **current user's** trusted root store.
- The local proxy uses that CA to decrypt HTTPS traffic **inside your PC**, filter it, and re-encrypt it.
  Nothing is sent to any Shoji server. There is no telemetry and no remote service.
- Hosts in `https_exclusions` (banks, payment, password managers, update services, … — editable in the
  dashboard) are never decrypted. Apps that reject the certificate (certificate pinning) are detected and
  passed through automatically.

## Protect the private key

`data/certs/mitmproxy-ca.pem` contains the CA's **private key**. Anyone who obtains it could impersonate
any website to *your* PC.

- Never share, upload or commit the `data/` folder (it is in `.gitignore`).
- Don't copy your `data/certs` to another PC. Let each PC generate its own.
- To stop using Shoji: delete the certificate in `certmgr.msc` → *Trusted Root Certification Authorities*
  → *Certificates* (look for *Shoji Local Filtering CA* or *mitmproxy*), then delete `data/certs`.

## Network exposure

By default every listener binds to `127.0.0.1` only (proxy 8080, DNS 53, dashboard 8765).
If you change `proxy.listen_host` / `dns.listen_host` to `0.0.0.0` to serve phones on your LAN, other
devices on that network can use your proxy and DNS. Only do this on a network you trust, and keep the
Windows Firewall rule limited to *Private* networks. The dashboard should stay on `127.0.0.1`.

## Reporting a vulnerability

Please **do not open a public issue** for security problems. Use GitHub's
[private vulnerability reporting](../../security/advisories/new) for this repository instead.
We aim to acknowledge reports within 7 days.
