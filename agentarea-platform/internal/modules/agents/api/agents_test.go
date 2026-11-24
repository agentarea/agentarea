package api

import (
	"slices"
	"testing"
)

func TestPage(t *testing.T) {
	items := []int{1, 2, 3, 4, 5}
	for _, tc := range []struct {
		limit, offset int
		want          []int
	}{
		{50, 0, items},
		{2, 0, []int{1, 2}},
		{2, 3, []int{4, 5}},
		{2, 4, []int{5}},
		{2, 9, []int{}},
		{0, 0, []int{}},
		{-1, -1, []int{}},
		{2, -3, []int{1, 2}},
	} {
		if got := Page(items, tc.limit, tc.offset); !slices.Equal(got, tc.want) {
			t.Errorf("Page(%d, %d) = %v, want %v", tc.limit, tc.offset, got, tc.want)
		}
	}
}
