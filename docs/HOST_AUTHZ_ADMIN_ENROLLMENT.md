# Host-admin grant enrollment (source candidate)

`vera_core.host_authz.admin_enrollment.HostAdminEnrollmentServer` is a
Linux-only, fail-closed reference for the separate administrative operation
required before `UnifiedWitnessLeader` can authorize a signed grant.

It has **not** been installed or qualified on Lappy, VN1, VN2, or the NAS.

## Security boundary

- The leader process holds the existing verifier and leader database. The
  administrator never receives the leader signing key or a model-visible RPC.
- An OS launcher must pin one dedicated administrator UID, GID, PID and process
  start time, distinct from the host, every bound model, and providers.
- Linux `SO_PEERCRED` and per-message `SCM_CREDENTIALS` must agree with the
  launcher pin; an inherited descriptor cannot confer administrator identity.
- The socket directory and socket must be owned by the leader process, with
  access restricted to the administrator group. Group access alone never
  authorizes a sender; the exact kernel UID/PID/start must also agree.
- The only permitted request carries a canonical issuer-signed grant. The
  independent leader checks signature, time, model/provider binding and
  positive consent, then durably registers it. The witness's public mTLS
  endpoint does **not** expose enrollment.
- A private journal durably records the request digest before leader mutation.
  It stores no raw signed grant. Duplicate requests fail closed. A crash or
  post-commit lost response leaves a `PENDING` attempt requiring readback and
  explicit reconciliation; an automatic retry is prohibited.

## Qualification still required

1. Actually provision separate OS accounts, group membership, private leader
   state, administrator socket, service lifecycle and a protected launch path.
2. Bind registration to real consent origin and prove revocations before START
   deny subsequent effects; positive consent observed before registration is
   not sufficient forever.
3. Test restart, credential rotation, hard process crashes, inode replacement,
   inherited file descriptors, and use of two competing leader copies on real
   hosts. A cloned leader DB **plus signing key** remains a material failing
   trust boundary; this enrollment reference does not fix it.
4. Implement and physically qualify an equivalent Windows host-admin transport
   before attempting Windows deployment. There is no TCP or user-token
   fallback here.

Passing synthetic and Linux forked-process tests is **TEST** evidence only;
it does not establish actual host key custody, authorized consent provenance,
or a production enrollment administrator.
