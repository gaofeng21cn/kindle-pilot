# Agent workflow

The normal request shape is:

~~~text
Inspect my connected Kindle and prepare the supported route.
~~~

The Agent should:

1. Run read-only USB discovery.
2. Ask for or read the exact firmware shown by the user.
3. Resolve the route and stop if the model or firmware is unknown.
4. Download only the declared upstream assets, then verify SHA-256.
5. Explain the next Kindle-screen action and wait for the observed evidence.
6. Use one MTP client and one batch session for a write plan.
7. Read back storage, paths, and byte sizes after each transfer group.
8. Record a step only when the evidence matches the step contract.
9. Treat QR login and book opening as separate runtime checks.

The Agent may resume a workflow from the state JSON. It must not infer a completed manual step from the presence of a downloaded file or from a successful process exit.
