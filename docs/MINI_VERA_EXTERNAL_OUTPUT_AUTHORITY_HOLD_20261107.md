# Mini-Vera external evaluation output: source hardening and host custody hold

Status: **SOURCE + SYNTHETIC TEST ONLY**. No authenticated host-owned output
directory issuer, Windows private ACL witness, external human rater, or Lappy
runtime qualification has been established.

## Linux parent-directory substitution

At the previous PR #201 head, the writer resolved an external output path,
then opened its parent. A deterministic test renamed the initially approved
parent directory and installed a second directory at the *same* pathname
inside that check. The tool wrote the output file into the replacement parent;
path equality did not establish directory identity.

The Linux writer now opens the requested parent directory **before** invoking
the separate path check; holds that exact descriptor; checks its live opened
target against the resolved path; and creates the child via `dir_fd` with
`O_EXCL | O_NOFOLLOW` and mode `0600`. The same-path replacement performed
between opening the first parent and path verification is rejected before
child creation, and the regression fails on the preceding code. Output
readback stays on the same descriptor.

An additional independent adversarial replay moved that *already pinned*
parent after the pre-create path check and immediately before the `dir_fd`
child creation. The prior source returned success even though the file was
created in the renamed directory. A second check of the pinned parent's
opened final path **after writing and same-descriptor readback** now returns a
typed custody refusal if the directory moved. The deterministic regression
proves rejection, and explicitly confirms that the bytes **were already
written** to the renamed directory. No cleanup or rollback is presumed.

This narrows an in-process race. It does **not** establish an independently
authorized parent. An actor able to replace the directory **before the first
open**, replace and restore the same path between checks, change custody after
the program exits, or operate as an equivalent privileged user remains outside
the local check's proof. A post-write refusal is *not* confidentiality or
atomicity evidence. Private human ratings,
case ownership and independently held commitments require externally managed
directory ownership, access control, and an independently held custody receipt.

## Windows source hold

The preceding Windows `NtCreateFile(FILE_CREATE)` source passed `None` for
`ObjectAttributes.SecurityDescriptor`. Inherited parent ACLs therefore
provided no guarantee that newly written evaluation output would be private.
Path/handle equality cannot attest effective child DACL. The writer now
**refuses Windows private evaluation output** with a typed hold instead of
creating an output file with unqualified permissions. This is an intentional
experimental compatibility break; it does not affect in-process aggregation
or descriptor-bound input validation.

Reactivation requires a trusted host-owned output parent with independently
verifiable identity, atomic child creation with explicit restrictive security
descriptor, native Windows tests for allowed and foreign-principal ACLs,
cross-process rename/rollback checks, and actual host readback. Synthetic
Linux tests and green CI on a different commit cannot substitute for that.

No existing output files, model weights, quarantined artifacts, credentials,
or running services were removed or modified as part of this source change.
