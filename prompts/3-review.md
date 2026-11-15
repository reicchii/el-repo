# Prompt 3: review another lane's pull request

Review pull request <number or branch>. This session did not write it. Do not edit its files.

Check, in this order:
1. Does it do the task in docs/PROJECT-CONTEXT.md section 12 and nothing more? Is the acceptance check output present and believable?
2. Correctness. Engine: units, coordinate epochs, pixel versus arcsecond, pixel quality (rejected bits at zero weight, bit 21 never masked), the like-with-like rule, errors propagated, CWAVE and CBAND used. ML: test split by sky tile, gold labels only in the test set, no leakage between splits, scores per brightness bin, calibration and conformal coverage reported, the 50% cap applied. Web: URL state round-trips, all four states exist, no invented data, numbers read from data products.
3. Contracts. Does anything read or write a field that is not in contracts/?
4. Language. Does every new string follow docs/PROJECT-CONTEXT.md section 5? Any reserved word misused? Any number without unit and origin?
5. Rules in AGENTS.md section 2. Any invented fact, dead control, forbidden licence, secret, or outside call beyond the allowlist?
6. Tests. Would the test fail if the code were wrong?

Report findings ordered by severity: blocker, should fix, note. For each: file and line, what is wrong, a concrete failing example, the fix in one sentence. If a level has no findings, say so. End with "merge" or "do not merge".
