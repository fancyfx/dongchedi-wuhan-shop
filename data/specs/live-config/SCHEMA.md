# AutoHome live config tree

Page-faithful parameter and equipment trees decoded from
`https://car.autohome.com.cn/config/spec/{spec_id}.html`.
Scoring rows stay in `data/specs/autohome-live-cache.json` and are not copied into these files.

## Tree file `live-config/{spec_id}.json`

- `schema_version`: `autohome-live-config-tree-1`
- `spec_id`, `title` (decoded 车型名称, otherwise the page title), `url`, `fetched_at` (ISO-8601)
- `legend`: standard `●`, optional `○`, absent `-`
- `sections`: page order, not sorted. Each section is `{name, group, items}`.

`group` is `param` (paramtypeitems), `config` (configtypeitems), `feature`, `ah100`, or `bag`.
Empty section names, empty item names, and sections with no items are omitted.
Bag groups with an empty `valueitems` list for the spec are skipped.

## Items and lines

Each item is `{name, value, lines?}`. `lines` is omitted for a plain single value.
A line is `{name, value, mark?}`. `mark` is only `standard` or `optional`.

- Parameter `displaytype !== 1`: decoded value; `0` or empty becomes `-`.
- Parameter `displaytype === 1`: one line per sublist entry. optiontype 1 values start with `●` (standard); optiontype 2 starts with `○` (optional); then the decoded subvalue (`0` or empty becomes `-`). `line.name` is the subname. `item.value` joins those line values with ` / `.
- Configuration with a sublist: subvalue `1` is standard and `line.value` is `●` (`标配` is not used as the line name); subvalue `2` is optional and `line.value` is `○` (`选配` is not used as the line name); any other subvalue uses the decoded subname for both `line.name` and `line.value`. `item.value` joins `● {name}` / `○ {name}` / `{name}` with ` / `. A price greater than 1 appends ` (¥N)` to that displayed line text. If no lines remain, the plain decoded value is used, or `-` when empty. `●` and `○` already in the text are kept.
- Configuration without a sublist: decoded value, or `-` when empty.

Nothing is invented and nothing is sorted.

## Index `live-config/index.json`

`schema_version`, `source` (`car.autohome.com.cn/config/spec`), `generated_at`, `legend`, `spec_count`, `specs`, and `sku_to_spec`.

`specs["49472"]` is `{title, url, section_count, item_count, file: "49472.json"}`.
`sku_to_spec` is built by scanning `listings-ranked.json`, `listings-filtered.json`, and `data-issues.json` for `specs.verification_sources[].spec_id` or a url matching `/config/spec/{id}.html`. Ids that are not in those sources are not added.

The same tree files and `index.json` are copied to `dashboard/public/data/live-config/`.

## Cache

`autohome-live-cache.json` keeps flat scoring `rows` only. It may store `section_count` but not `sections`.
A cache hit requires at least 30 rows and a tree file whose `sections` are non-empty.
A failed refetch keeps the previous rows and does not delete an existing good tree.
