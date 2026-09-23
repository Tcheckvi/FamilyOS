# F05-R2C Dynamic Interface and mDNS Network Binding

Date: 2026-09-23

Canonical baseline:

`957387f7f22ccd2f41bbb314d985fbf6459c61df`

## Purpose

This additive record materializes the qualified dynamic-interface and mDNS network-binding
contract for the synthetic MacBook witness. It does not rewrite the historical F05-R2C
candidate documents and it does not authorize live installation or production operation.

## Reboot and DHCP drift evidence

The real reboot qualification preserved the synthetic witness storage and continuity state,
but the MacBook LAN address changed from `192.168.1.182` to `192.168.1.192`.

Those two addresses are qualification evidence only. They are not repository configuration
and they must not appear as fixed LAN-address constants in the authoritative runner.

The pre-existing static-binding deployment therefore did not establish reboot-stable network
continuation. A service configuration tied to the pre-reboot address fails closed after DHCP
drift rather than silently widening its bind scope.

## Qualified dynamic-interface contract

The qualified no-install remediation uses:

- schema version `2`;
- an explicit `network_interface`;
- `bind_strategy=current_interface_ipv4`;
- an explicit `bind_port`;
- an independent `server_hostname`;
- no accepted `bind_ip` field.

At startup, the service resolves the configured interface to its current non-loopback IPv4
address and binds only to that address. It rejects absent, malformed, IPv6, loopback,
unspecified, and multicast interface results. It does not fall back to `0.0.0.0`.

While running, the service re-checks the interface address and fails closed if the selected
IPv4 changes.

## mDNS and TLS identity

The no-install qualification used the MacBook mDNS identity
`MacBook-Pro-von-xxx.local` from the Mac mini client side.

The existing transport contract remains unchanged: connection host discovery and TLS
`server_hostname` are separate inputs. The qualification preserved CA and hostname
verification and explicit server-leaf certificate fingerprint pinning.

No change to `src/familyos_pilot0/custody_mtls_transport.py` is required for this network
remediation.

## Witness-state preservation

The dynamic-interface and mDNS qualification was read-only with respect to witness state.
The bound state remained:

- checkpoint generation: `2`;
- checkpoint root digest:
  `5dda2751a63fffb93bec4895db15c46f865c6a0c2bc4ae6ad12b9ae1a7edce4d`;
- head sequence: `5`;
- head state digest:
  `79f1e700a70fe04ca5991392d76e7a717e0a1e1c9e79373060ebc6ed7eaa1206`;
- database SHA-256:
  `de550b4e59346306143f9e3ce8d8d845249e3b025f7f8c90154e82381cebb4be`;
- persistent-head SHA-256:
  `08ce7abb36c1fa43c10dc4015f4bfeb8d747c89b856950cb2eac56e509a64d08`.

No persistent witness-state mutation or USB-head mutation is authorized by this repository
materialization.

## Qualified inputs and evidence

Qualified runner candidate SHA-256:

`792b5218088aafd4ee7ee66777af16822553e09a90af42aa805a85e9bda06952`

Qualified machine-specific service-config instance SHA-256:

`18e4a301fa8cd7befc34e2a9addb207b8d8c4aff6e1cd91efffb160623e6cb6e`

No-install qualification final evidence SHA-256:

`a36b8b79be1d3c5e645cfdb7320313d8779ec2c43ed7f9d2f4d75aa2ff9d6216`

No-install qualification evidence manifest SHA-256:

`ff2bc9580c028504aca8895b7a214bbbd839a243762fbbd4ed1a4709be468752`

The machine-specific live `service.json` is not tracked. Its paths, USB identity,
credential paths and hashes, release references, and enrolled peer fingerprints remain
deployment inputs rather than repository constants.

## Repository materialization decision

The repository-authoritative materialization is bounded to:

```text
A  scripts/f05_r2c_synthetic_witness_service.py
A  tests/test_f05_r2c_synthetic_witness_service.py
A  docs/pilot0/F05-R2C-DYNAMIC-INTERFACE-MDNS-NETWORK-BINDING.md
```

The historical records below remain unchanged:

- `docs/pilot0/F05-R2C-SYNTHETIC-LAN-MTLS-USB-HEAD.md`;
- `docs/pilot0/F05-R2C-SYNTHETIC-MACBOOK-WITNESS.md`;
- `docs/pilot0/F05-RUNTIME-R2C-SUCCESSOR-CANDIDATE.md`.

The current LaunchAgent and live installation are external deployment artifacts. Switching
them to the repository-authoritative runner requires a separate controlled installation gate.

## Authorization boundaries

```text
QUALIFIED_DYNAMIC_BINDING_SOURCE_MATERIALIZED=true
STATIC_BIND_IP_IN_AUTHORITATIVE_RUNNER=false
CURRENT_INTERFACE_IPV4_FAIL_CLOSED=true
MDNS_CLIENT_DISCOVERY_CONTRACT_PRESERVED=true
TLS_HOSTNAME_VERIFICATION_PRESERVED=true
SERVER_CERTIFICATE_FINGERPRINT_PINNING_PRESERVED=true
LIVE_SERVICE_CONFIG_TRACKED=false
HISTORICAL_F05_R2C_DOCS_MUTATED=false
INSTALLATION_PERFORMED=false
PERSISTENT_STATE_MUTATION_PERFORMED=false
USB_HEAD_MUTATION_PERFORMED=false
PRODUCTION_APPROVAL=false
PUSH_AUTHORIZED=false
```
