package db

import "context"

// CountOne scans the single integer a counting query returns.
func CountOne(ctx context.Context, q Querier, sql string, args ...any) (int, error) {
	var n int64
	err := q.QueryRow(ctx, sql, args...).Scan(&n)
	return int(n), err
}

// CountBy scans (key text, count bigint) rows into a map; rows whose keys are equal add up.
func CountBy(ctx context.Context, q Querier, sql string, args ...any) (map[string]int, error) {
	rows, err := q.Query(ctx, sql, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := map[string]int{}
	for rows.Next() {
		var key string
		var n int64
		if err := rows.Scan(&key, &n); err != nil {
			return nil, err
		}
		out[key] += int(n)
	}
	return out, rows.Err()
}
