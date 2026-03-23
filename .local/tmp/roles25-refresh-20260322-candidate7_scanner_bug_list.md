# Refresh Triage Summary (roles25-refresh-20260322-candidate7)

## Scope

- Run label: `roles25-refresh-20260322-candidate7`
- Batch id: `20`
- Targets in batch: `25`
- Exclude role name containing `dummy`: `true`
- Exclude description prefixed `DEPRECATED:`: `true`
- URL list: `.local/tmp/roles25-refresh-20260322-candidate7_urls.txt`
- Bug target TSV: `.local/tmp/roles25-refresh-20260322-candidate7_bug_targets.tsv`

## Prioritized Scanner Bug Targets

| # | Target | unresolved | total_vars | ratio | dynamic_include | readme_only | no_static_def | ambiguous_set_fact |
|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | https://github.com/bertvv/ansible-role-bind | 57 | 96 | 0.594 | 0 | 44 | 13 | 4 |
| 2 | https://github.com/geerlingguy/ansible-role-postgresql | 41 | 68 | 0.603 | 0 | 34 | 7 | 9 |
| 3 | https://github.com/geerlingguy/ansible-role-mysql | 34 | 118 | 0.288 | 0 | 24 | 10 | 12 |
| 4 | https://github.com/geerlingguy/ansible-role-php | 29 | 121 | 0.240 | 0 | 18 | 11 | 14 |
| 5 | https://github.com/mshurutov/pgbackup | 22 | 37 | 0.595 | 0 | 0 | 22 | 0 |
| 6 | https://github.com/geerlingguy/ansible-role-nginx | 21 | 54 | 0.389 | 0 | 13 | 8 | 1 |
| 7 | https://github.com/geerlingguy/ansible-role-apache | 18 | 55 | 0.327 | 0 | 17 | 1 | 2 |
| 8 | https://github.com/dev-sec/ansible-ssh-hardening | 12 | 101 | 0.119 | 0 | 6 | 6 | 1 |
| 9 | https://github.com/mutl3y/ansible_port_listener | 10 | 13 | 0.769 | 0 | 0 | 10 | 0 |
| 10 | https://github.com/geerlingguy/ansible-role-nodejs | 6 | 16 | 0.375 | 0 | 6 | 0 | 1 |
| 11 | https://github.com/PrymalInstynct/ansible_auditd | 6 | 61 | 0.098 | 0 | 0 | 6 | 2 |
| 12 | https://github.com/geerlingguy/ansible-role-java | 3 | 5 | 0.600 | 0 | 2 | 1 | 1 |
| 13 | https://github.com/Splorgle/ansible-role-wireguard | 3 | 12 | 0.250 | 0 | 3 | 0 | 2 |
| 14 | https://github.com/weareinteractive/ansible-ssh | 3 | 15 | 0.200 | 1 | 0 | 2 | 0 |
| 15 | https://github.com/trippsc2/ansible-role-generate_csr | 3 | 29 | 0.103 | 0 | 0 | 3 | 0 |
| 16 | https://github.com/csakaszamok/ansible-role-rke2-after | 2 | 7 | 0.286 | 0 | 0 | 2 | 0 |
| 17 | https://github.com/trippsc2/ansible-role-ubuntu_seal_for_template | 1 | 7 | 0.143 | 0 | 0 | 0 | 0 |

## Suggested Buckets

- Bucket A: Dynamic include vars attribution
  - none
- Bucket B: README-only extraction over-capture
  - `https://github.com/bertvv/ansible-role-bind`
  - `https://github.com/geerlingguy/ansible-role-postgresql`
  - `https://github.com/geerlingguy/ansible-role-mysql`
  - `https://github.com/geerlingguy/ansible-role-php`
  - `https://github.com/geerlingguy/ansible-role-nginx`
  - `https://github.com/geerlingguy/ansible-role-apache`
  - `https://github.com/dev-sec/ansible-ssh-hardening`
  - `https://github.com/geerlingguy/ansible-role-nodejs`
  - `https://github.com/Splorgle/ansible-role-wireguard`
- Bucket C: No static definition false positives
  - `https://github.com/mshurutov/pgbackup`
  - `https://github.com/dev-sec/ansible-ssh-hardening`
  - `https://github.com/mutl3y/ansible_port_listener`
  - `https://github.com/PrymalInstynct/ansible_auditd`
  - `https://github.com/trippsc2/ansible-role-generate_csr`
- Bucket D: set_fact ambiguity inflation
  - `https://github.com/bertvv/ansible-role-bind`
  - `https://github.com/geerlingguy/ansible-role-postgresql`
  - `https://github.com/geerlingguy/ansible-role-mysql`
  - `https://github.com/geerlingguy/ansible-role-php`
