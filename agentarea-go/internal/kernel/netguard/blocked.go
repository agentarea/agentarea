package netguard

import "net/netip"

type addrRange struct {
	prefix netip.Prefix
	reason string
}

func prefixes(reason string, cidrs ...string) []addrRange {
	out := make([]addrRange, len(cidrs))
	for i, c := range cidrs {
		out[i] = addrRange{prefix: netip.MustParsePrefix(c), reason: reason}
	}
	return out
}

func addrs(list ...string) []netip.Addr {
	out := make([]netip.Addr, len(list))
	for i, a := range list {
		out[i] = netip.MustParseAddr(a)
	}
	return out
}

// tables are CPython 3.14's ipaddress special-purpose registries as
// _is_blocked_ip consults them: is_private (less its exceptions),
// is_loopback, is_link_local, is_reserved, is_multicast, is_unspecified
// and not is_global.
type tables struct {
	v4, v6                     []addrRange
	v4Exceptions, v6Exceptions []netip.Addr
	v6ExceptionNets            []netip.Prefix
}

func blockTables() tables {
	t := tables{}
	t.v4 = append(t.v4, prefixes("loopback", "127.0.0.0/8")...)
	t.v4 = append(t.v4, prefixes("link-local", "169.254.0.0/16")...)
	t.v4 = append(t.v4, prefixes("multicast", "224.0.0.0/4")...)
	t.v4 = append(t.v4, prefixes("reserved", "240.0.0.0/4", "255.255.255.255/32")...)
	t.v4 = append(t.v4, prefixes("private",
		"0.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.0.0.0/24", "192.0.0.170/31",
		"192.0.2.0/24", "192.168.0.0/16", "198.18.0.0/15", "198.51.100.0/24", "203.0.113.0/24")...)
	t.v4 = append(t.v4, prefixes("non-global", "100.64.0.0/10")...)
	t.v4Exceptions = addrs("192.0.0.9", "192.0.0.10")

	t.v6 = append(t.v6, prefixes("unspecified", "::/128")...)
	t.v6 = append(t.v6, prefixes("loopback", "::1/128")...)
	t.v6 = append(t.v6, prefixes("link-local", "fe80::/10")...)
	t.v6 = append(t.v6, prefixes("multicast", "ff00::/8")...)
	t.v6 = append(t.v6, prefixes("reserved",
		"::/8", "100::/8", "200::/7", "400::/6", "800::/5", "1000::/4", "4000::/3", "6000::/3",
		"8000::/3", "a000::/3", "c000::/3", "e000::/4", "f000::/5", "f800::/6", "fe00::/9")...)
	t.v6 = append(t.v6, prefixes("private",
		"::ffff:0:0/96", "64:ff9b:1::/48", "100::/64", "2001::/23", "2001:db8::/32", "2002::/16",
		"3fff::/20", "fc00::/7")...)
	t.v6Exceptions = addrs("2001:1::1", "2001:1::2")
	for _, c := range []string{"2001:3::/32", "2001:4:112::/48", "2001:20::/28", "2001:30::/28"} {
		t.v6ExceptionNets = append(t.v6ExceptionNets, netip.MustParsePrefix(c))
	}
	return t
}

// Blocked reports whether an address is non-public and why. An
// IPv4-mapped IPv6 address is judged as its IPv4 address.
//
// mcp-manager and event-service blocked a narrower set (loopback, RFC 1918
// and ULA, link-local, multicast, unspecified, 100.64.0.0/10); Python's,
// kept here, also refuses the documentation, benchmarking and reserved
// ranges, 0.0.0.0/8, the broadcast address, NAT64 local-use, 6to4 and
// the IETF protocol assignments.
func Blocked(a netip.Addr) (reason string, blocked bool) {
	a = a.WithZone("").Unmap()
	t := blockTables()
	if a.Is4() {
		for _, r := range t.v4 {
			if r.prefix.Contains(a) {
				if r.reason == "private" && contains(t.v4Exceptions, a) {
					continue
				}
				return r.reason, true
			}
		}
		return "", false
	}
	for _, r := range t.v6 {
		if r.prefix.Contains(a) {
			if r.reason == "private" && v6Exception(t, a) {
				continue
			}
			return r.reason, true
		}
	}
	return "", false
}

func contains(list []netip.Addr, a netip.Addr) bool {
	for _, x := range list {
		if x == a {
			return true
		}
	}
	return false
}

func v6Exception(t tables, a netip.Addr) bool {
	if contains(t.v6Exceptions, a) {
		return true
	}
	for _, n := range t.v6ExceptionNets {
		if n.Contains(a) {
			return true
		}
	}
	return false
}
