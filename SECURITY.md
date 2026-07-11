# Security Policy

## Reporting a vulnerability

Email **partner@chival.ai** with details. Please don't open a public issue for anything you believe is a real security vulnerability — give a chance to fix it before it's public.

Include, if you can:
- What the vulnerable behavior is and how you found it
- Steps to reproduce
- What you believe the impact is

## What's actually in scope

`chival-verify` is a local CLI tool. It executes arbitrary code you point it at (that's the entire point — grading a submission means running it) inside a sandbox (either a local `pytest` subprocess or an isolated Docker container). Realistic security concerns here look like:

- A sandbox escape — code run via `chival grade`/`chival certify` doing something it shouldn't be able to outside the sandbox boundary.
- The local sandbox backend's isolation being weaker than documented (it's explicitly not memory/CPU-capped or network-isolated the way the Docker backend is — this is a documented tradeoff, not a bug, but if you find it worse than documented, that's worth reporting).

Out of scope: vulnerabilities in `pytest`, Docker, or Python itself — report those upstream.

## Response time

This is a solo-maintained project. Real reports get a real response within a few days, not hours. If it's genuinely urgent (actively exploited, high severity), say so in the subject line.

## Supported versions

Only the latest released version is supported. There is no long-term-support branch at this stage.
