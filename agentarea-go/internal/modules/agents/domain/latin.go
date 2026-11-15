package domain

// latinBase maps the accented Latin letters NFKD splits to their ASCII base.
func latinBase() map[rune]string {
	groups := map[string]string{
		"a": "àáâãäåāăą", "A": "ÀÁÂÃÄÅĀĂĄ", "c": "çćĉċč", "C": "ÇĆĈĊČ", "d": "ď", "D": "Ď",
		"e": "èéêëēĕėęě", "E": "ÈÉÊËĒĔĖĘĚ", "g": "ĝğġģ", "G": "ĜĞĠĢ", "i": "ìíîïĩīĭį", "I": "ÌÍÎÏĨĪĬĮİ",
		"l": "ĺļľ", "L": "ĹĻĽ", "n": "ñńņň", "N": "ÑŃŅŇ", "o": "òóôõöōŏő", "O": "ÒÓÔÕÖŌŎŐ",
		"r": "ŕŗř", "R": "ŔŖŘ", "s": "śŝşš", "S": "ŚŜŞŠ", "t": "ţť", "T": "ŢŤ", "u": "ùúûüũūŭůűų", "U": "ÙÚÛÜŨŪŬŮŰŲ",
		"y": "ýÿ", "Y": "Ý", "z": "źżž", "Z": "ŹŻŽ",
	}
	m := map[rune]string{}
	for base, rs := range groups {
		for _, r := range rs {
			m[r] = base
		}
	}
	return m
}
