package domain

import "strings"

// splitext is posixpath.splitext.
func splitext(p string) (string, string) {
	sep := strings.LastIndexByte(p, '/')
	dot := strings.LastIndexByte(p, '.')
	if dot > sep {
		i := sep + 1
		for i < dot && p[i] == '.' {
			i++
		}
		if i < dot {
			return p[:dot], p[dot:]
		}
	}
	return p, ""
}

func suffixMap(ext string) string {
	switch ext {
	case ".svgz":
		return ".svg.gz"
	case ".tgz", ".taz", ".tz":
		return ".tar.gz"
	case ".tbz2":
		return ".tar.bz2"
	case ".txz":
		return ".tar.xz"
	}
	return ""
}

// GuessType is mimetypes.guess_type(path)[0] over Python 3.14's built-in
// table; "" when it knows none.
func GuessType(p string) string {
	base, ext := splitext(p)
	for s := suffixMap(strings.ToLower(ext)); s != ""; s = suffixMap(strings.ToLower(ext)) {
		base, ext = splitext(base + s)
	}
	switch ext {
	case ".gz", ".Z", ".bz2", ".xz", ".br":
		_, ext = splitext(base)
	}
	return typesMap(strings.ToLower(ext))
}

// ContentTypeOf is _guess_content_type: application/octet-stream when unknown.
func ContentTypeOf(p string) string {
	if ct := GuessType(p); ct != "" {
		return ct
	}
	return "application/octet-stream"
}

func typesMap(ext string) string {
	switch ext {
	case ".epub":
		return "application/epub+zip"
	case ".gz":
		return "application/gzip"
	case ".json":
		return "application/json"
	case ".webmanifest":
		return "application/manifest+json"
	case ".doc", ".dot", ".wiz":
		return "application/msword"
	case ".nq":
		return "application/n-quads"
	case ".nt":
		return "application/n-triples"
	case ".a", ".bin", ".dll", ".exe", ".o", ".obj", ".so":
		return "application/octet-stream"
	case ".oda":
		return "application/oda"
	case ".ogx":
		return "application/ogg"
	case ".pdf":
		return "application/pdf"
	case ".p7c":
		return "application/pkcs7-mime"
	case ".ai", ".eps", ".ps":
		return "application/postscript"
	case ".trig":
		return "application/trig"
	case ".m3u", ".m3u8":
		return "application/vnd.apple.mpegurl"
	case ".xlb", ".xls":
		return "application/vnd.ms-excel"
	case ".eot":
		return "application/vnd.ms-fontobject"
	case ".pot", ".ppa", ".pps", ".ppt", ".pwz":
		return "application/vnd.ms-powerpoint"
	case ".odg":
		return "application/vnd.oasis.opendocument.graphics"
	case ".odp":
		return "application/vnd.oasis.opendocument.presentation"
	case ".ods":
		return "application/vnd.oasis.opendocument.spreadsheet"
	case ".odt":
		return "application/vnd.oasis.opendocument.text"
	case ".pptx":
		return "application/vnd.openxmlformats-officedocument.presentationml.presentation"
	case ".xlsx":
		return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
	case ".docx":
		return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
	case ".rar":
		return "application/vnd.rar"
	case ".wasm":
		return "application/wasm"
	case ".7z":
		return "application/x-7z-compressed"
	case ".bcpio":
		return "application/x-bcpio"
	case ".cpio":
		return "application/x-cpio"
	case ".csh":
		return "application/x-csh"
	case ".deb":
		return "application/x-debian-package"
	case ".dvi":
		return "application/x-dvi"
	case ".gtar":
		return "application/x-gtar"
	case ".hdf":
		return "application/x-hdf"
	case ".h5":
		return "application/x-hdf5"
	case ".php":
		return "application/x-httpd-php"
	case ".latex":
		return "application/x-latex"
	case ".mif":
		return "application/x-mif"
	case ".cdf", ".nc":
		return "application/x-netcdf"
	case ".p12", ".pfx":
		return "application/x-pkcs12"
	case ".ram":
		return "application/x-pn-realaudio"
	case ".pyc", ".pyo":
		return "application/x-python-code"
	case ".rpm":
		return "application/x-rpm"
	case ".sh":
		return "application/x-sh"
	case ".shar":
		return "application/x-shar"
	case ".swf":
		return "application/x-shockwave-flash"
	case ".sv4cpio":
		return "application/x-sv4cpio"
	case ".sv4crc":
		return "application/x-sv4crc"
	case ".tar":
		return "application/x-tar"
	case ".tcl":
		return "application/x-tcl"
	case ".tex":
		return "application/x-tex"
	case ".texi", ".texinfo":
		return "application/x-texinfo"
	case ".roff", ".t", ".tr":
		return "application/x-troff"
	case ".man":
		return "application/x-troff-man"
	case ".me":
		return "application/x-troff-me"
	case ".ms":
		return "application/x-troff-ms"
	case ".ustar":
		return "application/x-ustar"
	case ".src":
		return "application/x-wais-source"
	case ".rdf", ".wsdl", ".xpdl", ".xsl":
		return "application/xml"
	case ".yaml", ".yml":
		return "application/yaml"
	case ".zip":
		return "application/zip"
	case ".3gp", ".3gpp":
		return "audio/3gpp"
	case ".3g2", ".3gpp2":
		return "audio/3gpp2"
	case ".aac", ".adts", ".ass", ".loas":
		return "audio/aac"
	case ".au", ".snd":
		return "audio/basic"
	case ".flac":
		return "audio/flac"
	case ".mka":
		return "audio/matroska"
	case ".m4a":
		return "audio/mp4"
	case ".mp2", ".mp3":
		return "audio/mpeg"
	case ".ogg":
		return "audio/ogg"
	case ".opus":
		return "audio/opus"
	case ".wav":
		return "audio/vnd.wave"
	case ".weba":
		return "audio/webm"
	case ".aif", ".aifc", ".aiff":
		return "audio/x-aiff"
	case ".ra":
		return "audio/x-pn-realaudio"
	case ".otf":
		return "font/otf"
	case ".ttf":
		return "font/ttf"
	case ".woff":
		return "font/woff"
	case ".woff2":
		return "font/woff2"
	case ".avif":
		return "image/avif"
	case ".bmp":
		return "image/bmp"
	case ".emf":
		return "image/emf"
	case ".fits":
		return "image/fits"
	case ".g3":
		return "image/g3fax"
	case ".gif":
		return "image/gif"
	case ".heic":
		return "image/heic"
	case ".heif":
		return "image/heif"
	case ".ief":
		return "image/ief"
	case ".jp2":
		return "image/jp2"
	case ".jpe", ".jpeg", ".jpg":
		return "image/jpeg"
	case ".jpm":
		return "image/jpm"
	case ".jpx":
		return "image/jpx"
	case ".png":
		return "image/png"
	case ".svg":
		return "image/svg+xml"
	case ".t38":
		return "image/t38"
	case ".tif", ".tiff":
		return "image/tiff"
	case ".tfx":
		return "image/tiff-fx"
	case ".ico":
		return "image/vnd.microsoft.icon"
	case ".webp":
		return "image/webp"
	case ".wmf":
		return "image/wmf"
	case ".ras":
		return "image/x-cmu-raster"
	case ".pnm":
		return "image/x-portable-anymap"
	case ".pbm":
		return "image/x-portable-bitmap"
	case ".pgm":
		return "image/x-portable-graymap"
	case ".ppm":
		return "image/x-portable-pixmap"
	case ".rgb":
		return "image/x-rgb"
	case ".xbm":
		return "image/x-xbitmap"
	case ".xpm":
		return "image/x-xpixmap"
	case ".xwd":
		return "image/x-xwindowdump"
	case ".eml", ".mht", ".mhtml", ".nws":
		return "message/rfc822"
	case ".gltf":
		return "model/gltf+json"
	case ".glb":
		return "model/gltf-binary"
	case ".stl":
		return "model/stl"
	case ".css":
		return "text/css"
	case ".csv":
		return "text/csv"
	case ".htm", ".html":
		return "text/html"
	case ".js", ".mjs":
		return "text/javascript"
	case ".markdown", ".md":
		return "text/markdown"
	case ".n3":
		return "text/n3"
	case ".bat", ".c", ".h", ".ksh", ".pl", ".srt", ".txt":
		return "text/plain"
	case ".rtx":
		return "text/richtext"
	case ".rtf":
		return "text/rtf"
	case ".tsv":
		return "text/tab-separated-values"
	case ".vtt":
		return "text/vtt"
	case ".py":
		return "text/x-python"
	case ".rst":
		return "text/x-rst"
	case ".etx":
		return "text/x-setext"
	case ".sgm", ".sgml":
		return "text/x-sgml"
	case ".vcf":
		return "text/x-vcard"
	case ".xml":
		return "text/xml"
	case ".mkv":
		return "video/matroska"
	case ".mk3d":
		return "video/matroska-3d"
	case ".mp4":
		return "video/mp4"
	case ".m1v", ".mpa", ".mpe", ".mpeg", ".mpg":
		return "video/mpeg"
	case ".ogv":
		return "video/ogg"
	case ".mov", ".qt":
		return "video/quicktime"
	case ".avi":
		return "video/vnd.avi"
	case ".webm":
		return "video/webm"
	case ".m4v":
		return "video/x-m4v"
	case ".wmv":
		return "video/x-ms-wmv"
	case ".movie":
		return "video/x-sgi-movie"
	}
	return ""
}
