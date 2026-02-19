local claims = std.extVar('claims');

{
  identity: {
    traits: {
      [if 'email' in claims && claims.email != null then 'email' else null]: claims.email,
      name: {
        [if 'name' in claims && claims.name != null then 'first' else null]:
          if 'name' in claims && claims.name != null then
            local parts = std.split(claims.name, ' ');
            if std.length(parts) > 0 then parts[0] else null
          else null,
        [if 'name' in claims && claims.name != null then 'last' else null]:
          if 'name' in claims && claims.name != null then
            local parts = std.split(claims.name, ' ');
            if std.length(parts) > 1 then std.join(' ', parts[1:]) else null
          else null,
      },
      [if 'login' in claims then 'username' else null]: claims.login,
    },
  },
}
