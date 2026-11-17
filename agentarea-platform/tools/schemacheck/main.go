// Command schemacheck is the Go half of the former Alembic comparison: it writes the goose
// baselines from a dump of the database Alembic builds (gen), builds a
// database with them (apply), and reduces a database to text two databases can
// be diffed on (normalize).
package main

import (
	"context"
	"database/sql"
	"errors"
	"flag"
	"fmt"
	"os"
	"regexp"
	"sort"
	"strings"

	"github.com/agentarea/agentarea/agentarea-platform/internal/schema"
)

func main() {
	if len(os.Args) < 2 {
		fmt.Fprintln(os.Stderr, "usage: schemacheck gen|apply|normalize [flags]")
		os.Exit(2)
	}
	var err error
	switch os.Args[1] {
	case "gen":
		err = runGen(os.Args[2:])
	case "apply":
		err = runApply(os.Args[2:])
	case "normalize":
		err = runNormalize(os.Args[2:])
	default:
		err = fmt.Errorf("unknown command %q", os.Args[1])
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, "schemacheck:", err)
		os.Exit(1)
	}
}

// Dated partitions are made at install time relative to now(), by the
// baseline's DO blocks just as by the Alembic revisions, so the files never
// carry them.
var (
	datedPartition = regexp.MustCompile(`^(stream_events_p[0-9]{8}|resource_usage_events_[0-9]{4}_[0-9]{2})`)
	datedToken     = regexp.MustCompile(`stream_events_p[0-9]{8}|resource_usage_events_[0-9]{4}_[0-9]{2}`)
)

// varcharIn matches pg_dump's text of `varchar_col IN ('a', 'b')`. Run again,
// that text parses to a different tree (each element cast to text), so the
// baseline carries the form that parses back to what the migrations made.
var varcharIn = regexp.MustCompile(`\(([a-z_][a-z0-9_]*)\)::text = ANY \(\(ARRAY\[((?:'(?:[^']|'')*'::character varying(?:, )?)+)\]\)::text\[\]\)`)

const corePartitions = `--
-- stream_events: daily partitions from yesterday through 14 days ahead (UTC), as 20261006_0900_event_streams makes them
--

DO $$
DECLARE
    day date;
BEGIN
    FOR i IN -1..14 LOOP
        day := (now() AT TIME ZONE 'UTC')::date + i;
        EXECUTE format(
            'CREATE TABLE IF NOT EXISTS public.%I PARTITION OF public.stream_events FOR VALUES FROM (%L) TO (%L)',
            'stream_events_p' || to_char(day, 'YYYYMMDD'),
            day::text || ' 00:00:00+00',
            (day + 1)::text || ' 00:00:00+00');
    END LOOP;
END
$$;`

const enterprisePartitions = `--
-- resource_usage_events: monthly partitions from this month through 12 ahead (UTC), as 20261021_1200_ledger_partitions makes them on an empty ledger
--

DO $$
DECLARE
    month date;
    name text;
BEGIN
    FOR month IN
        SELECT generate_series(
            date_trunc('month', now() AT TIME ZONE 'UTC'),
            date_trunc('month', now() AT TIME ZONE 'UTC') + interval '12 months',
            interval '1 month')::date
    LOOP
        name := 'resource_usage_events_' || to_char(month, 'YYYY_MM');
        EXECUTE format(
            'CREATE TABLE agentarea_enterprise.%I PARTITION OF agentarea_enterprise.resource_usage_events FOR VALUES FROM (%L) TO (%L)',
            name,
            month::timestamp AT TIME ZONE 'UTC',
            (month::timestamp + interval '1 month') AT TIME ZONE 'UTC');
        PERFORM agentarea_enterprise.resource_usage_events_guard_partition(name);
    END LOOP;
END
$$;`

const preamble = `SET LOCAL statement_timeout = 0;
SET LOCAL lock_timeout = 0;
SET LOCAL check_function_bodies = false;
SET LOCAL client_min_messages = warning;
SET LOCAL row_security = off;
SELECT pg_catalog.set_config('search_path', '', true);`

type block struct {
	Name, Type, Schema string
	Body               string
}

var header = regexp.MustCompile(`(?m)^--\n-- Name: (.*?); Type: (.*?); Schema: (.*?); Owner: .*\n--\n`)

// parseDump splits pg_dump --schema-only output into its TOC entries.
func parseDump(text string) []block {
	var lines []string
	for _, l := range strings.Split(text, "\n") {
		if strings.HasPrefix(l, `\restrict `) || strings.HasPrefix(l, `\unrestrict `) {
			continue
		}
		lines = append(lines, l)
	}
	text = strings.Join(lines, "\n")
	if i := strings.Index(text, "--\n-- PostgreSQL database dump complete"); i >= 0 {
		text = text[:i]
	}
	locs := header.FindAllStringSubmatchIndex(text, -1)
	blocks := make([]block, 0, len(locs))
	for i, loc := range locs {
		end := len(text)
		if i+1 < len(locs) {
			end = locs[i+1][0]
		}
		blocks = append(blocks, block{
			Name:   text[loc[2]:loc[3]],
			Type:   text[loc[4]:loc[5]],
			Schema: text[loc[6]:loc[7]],
			Body:   strings.TrimSpace(text[loc[1]:end]),
		})
	}
	return blocks
}

func (b block) render() string {
	return fmt.Sprintf("--\n-- Name: %s; Type: %s; Schema: %s\n--\n\n%s", b.Name, b.Type, b.Schema, b.Body)
}

func runGen(args []string) error {
	fl := flag.NewFlagSet("gen", flag.ExitOnError)
	dump := fl.String("dump", "", "pg_dump --schema-only --no-owner --no-privileges of the Alembic-built database")
	dsn := fl.String("dsn", "", "the Alembic-built database, for its reference rows")
	coreOut := fl.String("core", "", "core baseline to write")
	entOut := fl.String("enterprise", "", "enterprise baseline to write (empty: no enterprise schema)")
	entHead := fl.String("enterprise-head", "", "the enterprise Alembic head the dump stands at")
	_ = fl.Parse(args)
	if *entOut != "" && *entHead == "" {
		return errors.New("-enterprise needs -enterprise-head")
	}
	raw, err := os.ReadFile(*dump)
	if err != nil {
		return err
	}
	var core, ent []block
	for _, b := range parseDump(string(raw)) {
		if b.Type != "FUNCTION" && datedPartition.MatchString(b.Name) {
			continue
		}
		if b.Type != "FUNCTION" {
			b.Body = varcharIn.ReplaceAllString(b.Body, "$1 = ANY (ARRAY[$2])")
		}
		switch {
		case b.Type == "SCHEMA" && b.Name == "agentarea_enterprise":
			// schema.Migrate creates it before goose's version table goes in it.
		case b.Type == "EVENT TRIGGER" && strings.HasPrefix(b.Name, "resource_usage_"):
			ent = append(ent, b)
		case b.Schema == "agentarea_enterprise":
			ent = append(ent, b)
		case b.Schema == "public", b.Type == "EXTENSION", b.Type == "COMMENT" && strings.HasPrefix(b.Name, "EXTENSION "):
			if strings.Contains(b.Body, "agentarea_enterprise") {
				return fmt.Errorf("core object %s %s names the enterprise schema", b.Type, b.Name)
			}
			core = append(core, b)
		default:
			return fmt.Errorf("unclassified dump entry %s %q in schema %s", b.Type, b.Name, b.Schema)
		}
	}
	for _, b := range append(append([]block{}, core...), ent...) {
		if b.Type != "FUNCTION" && datedToken.MatchString(b.Body) {
			return fmt.Errorf("dated partition left in %s %s", b.Type, b.Name)
		}
	}

	db, err := schema.Open(*dsn)
	if err != nil {
		return err
	}
	defer func() { _ = db.Close() }()
	ctx := context.Background()

	coreRows, err := referenceRows(ctx, db, "public", schema.AlembicHead)
	if err != nil {
		return err
	}
	if err := writeBaseline(*coreOut, "core", schema.AlembicHead, core, corePartitions, "", coreRows); err != nil {
		return err
	}
	if *entOut == "" {
		return nil
	}
	if len(ent) == 0 {
		return errors.New("the dump has no enterprise schema")
	}
	entRows, err := referenceRows(ctx, db, "agentarea_enterprise", *entHead)
	if err != nil {
		return err
	}
	return writeBaseline(*entOut, "enterprise", *entHead, ent, enterprisePartitions, "EVENT TRIGGER", entRows)
}

// writeBaseline lays the entries out in pg_dump's order, the partition block
// before the first entry of type beforeType (or after the last entry), then
// the reference rows.
func writeBaseline(path, set, head string, blocks []block, partitions, beforeType string, rows []string) error {
	var sb strings.Builder
	fmt.Fprintf(&sb, "-- The %s schema at Alembic revision %s with the rows a fresh `alembic upgrade head` inserts.\n", set, head)
	sb.WriteString("-- Generated by tools/schemacheck/schemacheck.sh regen from pg_dump; do not edit. See internal/schema/README.md.\n\n")
	sb.WriteString("-- +goose Up\n-- +goose StatementBegin\n")
	sb.WriteString(preamble + "\n\n")
	placed := false
	for _, b := range blocks {
		if !placed && beforeType != "" && b.Type == beforeType {
			sb.WriteString(partitions + "\n\n\n")
			placed = true
		}
		sb.WriteString(b.render() + "\n\n\n")
	}
	if !placed {
		sb.WriteString(partitions + "\n\n\n")
	}
	sb.WriteString("--\n-- Reference rows\n--\n\n")
	for _, r := range rows {
		sb.WriteString(r + "\n")
	}
	sb.WriteString("-- +goose StatementEnd\n\n")
	sb.WriteString("-- +goose Down\n-- +goose StatementBegin\n")
	fmt.Fprintf(&sb, "DO $$ BEGIN RAISE EXCEPTION 'the %s baseline (Alembic %s) is not reversible'; END $$;\n", set, head)
	sb.WriteString("-- +goose StatementEnd\n")
	return os.WriteFile(path, []byte(sb.String()), 0o644)
}

type column struct {
	Name, Type string
}

// volatile reports whether a column takes a fresh value per install: the
// migrations insert gen_random_uuid() ids and now() timestamps.
func volatile(c column) string {
	switch {
	case c.Name == "id" && c.Type == "uuid":
		return "gen_random_uuid()"
	case (c.Name == "created_at" || c.Name == "updated_at") && strings.HasPrefix(c.Type, "timestamp"):
		return "now()"
	}
	return ""
}

type table struct {
	Name    string
	Columns []column
}

// tablesWithRows lists the schema's non-empty tables, referenced tables first.
func tablesWithRows(ctx context.Context, db *sql.DB, schemaName string) ([]table, error) {
	rows, err := db.QueryContext(ctx, `
		SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
		WHERE n.nspname = $1 AND c.relkind IN ('r', 'p') AND NOT c.relispartition
		AND c.relname NOT LIKE 'goose_db_version%'
		ORDER BY c.relname`, schemaName)
	if err != nil {
		return nil, err
	}
	var names []string
	for rows.Next() {
		var n string
		if err := rows.Scan(&n); err != nil {
			return nil, err
		}
		names = append(names, n)
	}
	_ = rows.Close()

	byName := map[string]*table{}
	var order []string
	for _, n := range names {
		var any bool
		q := fmt.Sprintf("SELECT EXISTS (SELECT 1 FROM %s.%s)", ident(schemaName), ident(n))
		if err := db.QueryRowContext(ctx, q).Scan(&any); err != nil {
			return nil, err
		}
		if !any {
			continue
		}
		cols, err := db.QueryContext(ctx, `
			SELECT a.attname, format_type(a.atttypid, a.atttypmod)
			FROM pg_attribute a
			WHERE a.attrelid = format('%I.%I', $1::text, $2::text)::regclass
			AND a.attnum > 0 AND NOT a.attisdropped AND a.attgenerated = ''
			ORDER BY a.attnum`, schemaName, n)
		if err != nil {
			return nil, err
		}
		t := &table{Name: n}
		for cols.Next() {
			var c column
			if err := cols.Scan(&c.Name, &c.Type); err != nil {
				return nil, err
			}
			t.Columns = append(t.Columns, c)
		}
		_ = cols.Close()
		byName[n] = t
		order = append(order, n)
	}

	// Foreign keys among the non-empty tables: a referenced table goes first,
	// and a reference to a column given a fresh value per install is refused.
	fks, err := db.QueryContext(ctx, `
		SELECT src.relname, dst.relname, a.attname
		FROM pg_constraint k
		JOIN pg_class src ON src.oid = k.conrelid
		JOIN pg_class dst ON dst.oid = k.confrelid
		JOIN pg_namespace n ON n.oid = src.relnamespace
		JOIN pg_attribute a ON a.attrelid = k.confrelid AND a.attnum = ANY (k.confkey)
		WHERE k.contype = 'f' AND n.nspname = $1`, schemaName)
	if err != nil {
		return nil, err
	}
	deps := map[string][]string{}
	for fks.Next() {
		var src, dst, col string
		if err := fks.Scan(&src, &dst, &col); err != nil {
			return nil, err
		}
		if byName[src] == nil || byName[dst] == nil || src == dst {
			continue
		}
		for _, c := range byName[dst].Columns {
			if c.Name == col && volatile(c) != "" {
				return nil, fmt.Errorf("%s references %s.%s, which the baseline gives a fresh value", src, dst, col)
			}
		}
		deps[src] = append(deps[src], dst)
	}
	_ = fks.Close()

	var sorted []table
	done := map[string]bool{}
	var visit func(string, int) error
	visit = func(n string, depth int) error {
		if done[n] {
			return nil
		}
		if depth > len(order) {
			return fmt.Errorf("foreign key cycle through %s", n)
		}
		for _, d := range deps[n] {
			if err := visit(d, depth+1); err != nil {
				return err
			}
		}
		done[n] = true
		sorted = append(sorted, *byName[n])
		return nil
	}
	for _, n := range order {
		if err := visit(n, 0); err != nil {
			return nil, err
		}
	}
	return sorted, nil
}

// referenceRows renders every row of the schema's non-empty tables as an
// INSERT, the Alembic version table included, and checks the version.
func referenceRows(ctx context.Context, db *sql.DB, schemaName, head string) ([]string, error) {
	tables, err := tablesWithRows(ctx, db, schemaName)
	if err != nil {
		return nil, err
	}
	var out []string
	sawHead := false
	for _, t := range tables {
		values, err := selectText(ctx, db, schemaName, t)
		if err != nil {
			return nil, err
		}
		names := make([]string, len(t.Columns))
		for i, c := range t.Columns {
			names[i] = ident(c.Name)
		}
		for _, row := range values {
			lits := make([]string, len(row))
			for i, v := range row {
				switch {
				case volatile(t.Columns[i]) != "":
					lits[i] = volatile(t.Columns[i])
				case v == nil:
					lits[i] = "NULL"
				default:
					lits[i] = literal(*v)
				}
				if strings.HasPrefix(t.Name, "alembic_version") && v != nil && *v == head {
					sawHead = true
				}
			}
			out = append(out, fmt.Sprintf("INSERT INTO %s.%s (%s) VALUES (%s);",
				ident(schemaName), ident(t.Name), strings.Join(names, ", "), strings.Join(lits, ", ")))
		}
	}
	if !sawHead {
		return nil, fmt.Errorf("%s is not at Alembic %s; update the head constant in internal/schema/schema.go", schemaName, head)
	}
	return out, nil
}

func selectText(ctx context.Context, db *sql.DB, schemaName string, t table) ([][]*string, error) {
	exprs := make([]string, len(t.Columns))
	var stable, fresh []string
	for i, c := range t.Columns {
		exprs[i] = ident(c.Name) + "::text"
		if volatile(c) == "" {
			stable = append(stable, exprs[i])
		} else {
			fresh = append(fresh, exprs[i])
		}
	}
	// Per-install values sort last, so the order is the same on every install.
	q := fmt.Sprintf("SELECT %s FROM %s.%s ORDER BY %s", strings.Join(exprs, ", "),
		ident(schemaName), ident(t.Name), strings.Join(append(stable, fresh...), ", "))
	rows, err := db.QueryContext(ctx, q)
	if err != nil {
		return nil, err
	}
	defer func() { _ = rows.Close() }()
	var out [][]*string
	for rows.Next() {
		row := make([]*string, len(t.Columns))
		ptrs := make([]any, len(row))
		for i := range row {
			ptrs[i] = &row[i]
		}
		if err := rows.Scan(ptrs...); err != nil {
			return nil, err
		}
		out = append(out, row)
	}
	return out, rows.Err()
}

// runApply migrates each set to its baseline only: the check compares the
// baselines with the Alembic head, and later goose files move past it.
func runApply(args []string) error {
	fl := flag.NewFlagSet("apply", flag.ExitOnError)
	dsn := fl.String("dsn", "", "database to migrate")
	entDir := fl.String("enterprise-dir", "", "the enterprise set's goose directory (agentarea-enterprise/platform/migrations); empty: core only")
	entHead := fl.String("enterprise-head", "", "the enterprise Alembic head")
	_ = fl.Parse(args)
	if *entDir != "" && *entHead == "" {
		return errors.New("-enterprise-dir needs -enterprise-head")
	}
	db, err := schema.Open(*dsn)
	if err != nil {
		return err
	}
	defer func() { _ = db.Close() }()
	ctx := context.Background()
	core := schema.Core()
	core.UpTo = schema.BaselineVersion
	if err := schema.Migrate(ctx, db, core); err != nil {
		return err
	}
	if *entDir != "" {
		set := schema.Extension("enterprise", os.DirFS(*entDir), "agentarea_enterprise",
			"agentarea_enterprise.alembic_version_enterprise", *entHead)
		set.UpTo = schema.BaselineVersion
		return schema.Migrate(ctx, db, set)
	}
	return nil
}

// runNormalize writes the dump's entries sorted, goose's own tables left out,
// then every row of every non-empty table with per-install values masked, and
// the indexes that are not valid.
func runNormalize(args []string) error {
	fl := flag.NewFlagSet("normalize", flag.ExitOnError)
	dump := fl.String("dump", "", "pg_dump --schema-only --no-owner --no-privileges output")
	dsn := fl.String("dsn", "", "the dumped database")
	out := fl.String("out", "", "file to write")
	_ = fl.Parse(args)
	raw, err := os.ReadFile(*dump)
	if err != nil {
		return err
	}
	var entries []string
	for _, b := range parseDump(string(raw)) {
		if strings.Contains(b.Name, "goose_db_version") || strings.Contains(b.Body, "goose_db_version") {
			continue
		}
		entries = append(entries, b.render())
	}
	sort.Strings(entries)

	db, err := schema.Open(*dsn)
	if err != nil {
		return err
	}
	defer func() { _ = db.Close() }()
	ctx := context.Background()
	var rowLines []string
	for _, s := range []string{"public", "agentarea_enterprise"} {
		tables, err := tablesWithRows(ctx, db, s)
		if err != nil {
			return err
		}
		for _, t := range tables {
			values, err := selectText(ctx, db, s, t)
			if err != nil {
				return err
			}
			for _, row := range values {
				cells := make([]string, len(row))
				for i, v := range row {
					switch {
					case v == nil:
						cells[i] = t.Columns[i].Name + "=NULL"
					case volatile(t.Columns[i]) != "":
						cells[i] = t.Columns[i].Name + "=<" + volatile(t.Columns[i]) + ">"
					default:
						cells[i] = t.Columns[i].Name + "=" + literal(*v)
					}
				}
				rowLines = append(rowLines, s+"."+t.Name+": "+strings.Join(cells, ", "))
			}
		}
	}
	sort.Strings(rowLines)

	invalid, err := db.QueryContext(ctx, `
		SELECT i.indexrelid::regclass::text FROM pg_index i
		WHERE NOT (i.indisvalid AND i.indisready AND i.indislive) ORDER BY 1`)
	if err != nil {
		return err
	}
	var bad []string
	for invalid.Next() {
		var n string
		if err := invalid.Scan(&n); err != nil {
			return err
		}
		bad = append(bad, "invalid index: "+n)
	}
	_ = invalid.Close()

	text := strings.Join(entries, "\n\n") + "\n\n-- rows\n" + strings.Join(rowLines, "\n") + "\n" + strings.Join(bad, "\n") + "\n"
	return os.WriteFile(*out, []byte(text), 0o644)
}

func ident(s string) string {
	return `"` + strings.ReplaceAll(s, `"`, `""`) + `"`
}

func literal(s string) string {
	if strings.Contains(s, `\`) {
		return "E'" + strings.ReplaceAll(strings.ReplaceAll(s, `\`, `\\`), "'", "''") + "'"
	}
	return "'" + strings.ReplaceAll(s, "'", "''") + "'"
}
