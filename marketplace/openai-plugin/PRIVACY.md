# Privacy Policy — DSG Verified Execution

DSG Verified Execution processes the bounded execution facts a user submits for verification, including execution identifiers, optional trace identifiers, hashed plan/action references, verification flags, and optional cost information.

The plugin is designed not to require source code, passwords, private keys, payment-card data, or solver credentials. Users should not submit secrets or unnecessary personal data.

A live verification request may be sent to the DSG Cinema verification service configured by `DSG_VERIFY_URL`. The service uses the submitted facts to derive a bounded deterministic verification problem and returns a Proof Receipt. The public verification route does not accept arbitrary solver programs and does not expose the backend Z3 credential.

Operational logs may contain technical request metadata needed for service reliability and security. The Proof Receipt may contain execution/trace identifiers and hashes supplied or derived from the request.

This policy does not claim a specific certification or regulatory status. Before public submission, the publisher should confirm production retention, deletion, contact, and jurisdiction details and update this page to match the deployed service exactly.
