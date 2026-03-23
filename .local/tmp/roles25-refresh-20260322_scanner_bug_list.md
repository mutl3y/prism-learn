# Refresh Triage Summary (roles25-refresh-20260322)

## Scope

- Run label: `roles25-refresh-20260322`
- Batch id: `8`
- Targets in batch: `25`
- Exclude role name containing `dummy`: `true`
- Exclude description prefixed `DEPRECATED:`: `true`
- URL list: `.local/tmp/roles25-refresh-20260322_urls.txt`
- Bug target TSV: `.local/tmp/roles25-refresh-20260322_bug_targets.tsv`

## Prioritized Scanner Bug Targets

| # | Target | unresolved | total_vars | ratio | dynamic_include | readme_only | no_static_def | ambiguous_set_fact |
|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | https://github.com/geerlingguy/ansible-role-mysql | 51 | 126 | 0.405 | 22 | 29 | 0 | 12 |
| 2 | https://github.com/geerlingguy/ansible-role-php | 48 | 134 | 0.358 | 29 | 19 | 0 | 14 |
| 3 | https://github.com/bertvv/ansible-role-bind | 42 | 77 | 0.545 | 21 | 21 | 0 | 4 |
| 4 | https://github.com/mshurutov/pgbackup | 37 | 48 | 0.771 | 0 | 0 | 37 | 0 |
| 5 | https://github.com/geerlingguy/ansible-role-postgresql | 30 | 55 | 0.545 | 17 | 13 | 0 | 9 |
| 6 | https://github.com/geerlingguy/ansible-role-nginx | 27 | 59 | 0.458 | 14 | 13 | 0 | 1 |
| 7 | https://github.com/PrymalInstynct/ansible_auditd | 20 | 64 | 0.312 | 20 | 0 | 0 | 2 |
| 8 | https://github.com/dev-sec/ansible-ssh-hardening | 19 | 105 | 0.181 | 13 | 6 | 0 | 1 |
| 9 | https://github.com/geerlingguy/ansible-role-apache | 18 | 54 | 0.333 | 4 | 14 | 0 | 2 |
| 10 | https://github.com/geerlingguy/ansible-role-nodejs | 13 | 20 | 0.650 | 0 | 7 | 6 | 1 |
| 11 | https://github.com/mutl3y/ansible_port_listener | 12 | 13 | 0.923 | 0 | 0 | 12 | 0 |
| 12 | https://github.com/csakaszamok/ansible-role-rke2-after | 9 | 9 | 1.000 | 0 | 0 | 9 | 0 |
| 13 | https://github.com/geerlingguy/ansible-role-java | 5 | 7 | 0.714 | 3 | 2 | 0 | 1 |
| 14 | https://github.com/weareinteractive/ansible-ssh | 4 | 16 | 0.250 | 4 | 0 | 0 | 0 |
| 15 | https://github.com/Splorgle/ansible-role-wireguard | 3 | 12 | 0.250 | 0 | 3 | 0 | 2 |
| 16 | https://github.com/trippsc2/ansible-role-generate_csr | 3 | 29 | 0.103 | 3 | 0 | 0 | 0 |
| 17 | https://github.com/trippsc2/ansible-role-ubuntu_seal_for_template | 2 | 7 | 0.286 | 0 | 0 | 1 | 0 |
| 18 | https://github.com/sv0/ansible-secure | 1 | 6 | 0.167 | 0 | 0 | 1 | 0 |
| 19 | https://github.com/trippsc2/ansible-role-join_testing_ad_domain | 1 | 11 | 0.091 | 0 | 0 | 1 | 0 |

## Suggested Buckets

- Bucket A: Dynamic include vars attribution
  - `https://github.com/geerlingguy/ansible-role-mysql`
  - `https://github.com/geerlingguy/ansible-role-php`
  - `https://github.com/bertvv/ansible-role-bind`
  - `https://github.com/geerlingguy/ansible-role-postgresql`
  - `https://github.com/geerlingguy/ansible-role-nginx`
  - `https://github.com/PrymalInstynct/ansible_auditd`
  - `https://github.com/dev-sec/ansible-ssh-hardening`
  - `https://github.com/geerlingguy/ansible-role-java`
  - `https://github.com/weareinteractive/ansible-ssh`
  - `https://github.com/trippsc2/ansible-role-generate_csr`
- Bucket B: README-only extraction over-capture
  - `https://github.com/geerlingguy/ansible-role-mysql`
  - `https://github.com/geerlingguy/ansible-role-php`
  - `https://github.com/bertvv/ansible-role-bind`
  - `https://github.com/geerlingguy/ansible-role-postgresql`
  - `https://github.com/geerlingguy/ansible-role-nginx`
  - `https://github.com/dev-sec/ansible-ssh-hardening`
  - `https://github.com/geerlingguy/ansible-role-apache`
  - `https://github.com/geerlingguy/ansible-role-nodejs`
  - `https://github.com/Splorgle/ansible-role-wireguard`
- Bucket C: No static definition false positives
  - `https://github.com/mshurutov/pgbackup`
  - `https://github.com/geerlingguy/ansible-role-nodejs`
  - `https://github.com/mutl3y/ansible_port_listener`
  - `https://github.com/csakaszamok/ansible-role-rke2-after`
- Bucket D: set_fact ambiguity inflation
  - `https://github.com/geerlingguy/ansible-role-mysql`
  - `https://github.com/geerlingguy/ansible-role-php`
  - `https://github.com/bertvv/ansible-role-bind`
  - `https://github.com/geerlingguy/ansible-role-postgresql`
