#!/usr/bin/env python3
import json
from pathlib import Path

SCHEMA_URL = "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json"
REGISTRY_ROOT = Path("mcp-registry")


def infer_transport(url: str) -> str:
    if url.endswith("/sse"):
        return "sse"
    return "streamable-http"


def make_server(name, title, description, website, url, version="1.0.0"):
    transport = infer_transport(url)
    return {
        "$schema": SCHEMA_URL,
        "name": name,
        "description": description,
        "title": title,
        "websiteUrl": website,
        "version": version,
        "remotes": [
            {
                "type": transport,
                "url": url
            }
        ]
    }


SERVERS = [
    ("com.google.cloud.bigquery", "BigQuery", "Google Cloud BigQuery remote MCP server.", "https://cloud.google.com/bigquery", "bigquery.googleapis.com/mcp"),
    ("com.google.cloud.compute", "Compute Engine", "Google Cloud Compute Engine remote MCP server.", "https://cloud.google.com/compute", "compute.googleapis.com/mcp"),
    ("com.google.cloud.container", "GKE", "Google Kubernetes Engine remote MCP server.", "https://cloud.google.com/kubernetes-engine", "container.googleapis.com/mcp"),
    ("com.google.maps.grounding-lite", "Google Maps Grounding Lite", "Google Maps remote MCP server.", "https://developers.google.com/maps", "mapstools.googleapis.com/mcp"),
    ("com.asana.mcp", "Asana", "Asana project management remote MCP server.", "https://asana.com", "https://mcp.asana.com/sse"),
    ("com.airtable.mcp", "Airtable", "Airtable remote MCP server.", "https://airtable.com", "https://mcp.airtable.com/mcp"),
    ("com.box.mcp", "Box", "Box document management remote MCP server.", "https://box.com", "https://mcp.box.com"),
    ("com.canva.mcp", "Canva", "Canva design platform remote MCP server.", "https://canva.com", "https://mcp.canva.com/mcp"),
    ("com.dropbox.mcp", "Dropbox", "Dropbox remote MCP server.", "https://dropbox.com", "https://mcp.dropbox.com/mcp"),
    ("com.dropbox.dash", "Dropbox Dash", "Dropbox Dash remote MCP server.", "https://dropbox.com/dash", "https://mcp.dropbox.com/dash"),
    ("com.egnyte.mcp", "Egnyte", "Egnyte document management remote MCP server.", "https://egnyte.com", "https://mcp-server.egnyte.com/sse"),
    ("com.figma.mcp", "Figma", "Figma collaborative design remote MCP server.", "https://figma.com", "https://mcp.figma.com/mcp"),
    ("com.fireflies.mcp", "Firefly", "Fireflies.ai meeting intelligence remote MCP server.", "https://fireflies.ai", "https://api.fireflies.ai/mcp"),
    ("com.google.calendar", "Google Calendar", "Google Calendar remote MCP server.", "https://calendar.google.com", "Google remote MCP"),
    ("com.google.docs", "Google Docs", "Google Docs remote MCP server.", "https://docs.google.com", "Google remote MCP"),
    ("com.google.drive", "Google Drive", "Google Drive remote MCP server.", "https://drive.google.com", "Google remote MCP"),
    ("com.google.gmail", "Gmail", "Gmail remote MCP server.", "https://gmail.com", "Google remote MCP"),
    ("com.google.sheets", "Google Sheets", "Google Sheets remote MCP server.", "https://sheets.google.com", "Google remote MCP"),
    ("com.intercom.mcp", "Intercom", "Intercom customer support remote MCP server.", "https://intercom.com", "https://mcp.intercom.com/sse"),
    ("com.jam.mcp", "Jam", "Jam.dev bug reporting remote MCP server.", "https://jam.dev", "https://mcp.jam.dev/mcp"),
    ("com.kollektiv.mcp", "Kollektiv", "Kollektiv documentation remote MCP server.", "https://thekollektiv.ai", "https://mcp.thekollektiv.ai/sse"),
    ("com.linear.mcp", "Linear", "Linear project management remote MCP server.", "https://linear.app", "https://mcp.linear.app/sse"),
    ("com.listenetic.mcp", "Listenetic", "Listenetic productivity remote MCP server.", "https://app.listenetic.com", "https://mcp.listenetic.com/v1/mcp"),
    ("com.meta.ads", "Meta Ads", "Meta Ads remote MCP server.", "https://pipeboard.co", "https://mcp.pipeboard.co/meta-ads-mcp"),
    ("com.monday.mcp", "monday.com", "monday.com work OS remote MCP server.", "https://monday.com", "https://mcp.monday.com/sse"),
    ("com.notion.mcp", "Notion", "Notion workspace remote MCP server.", "https://notion.so", "https://mcp.notion.com/sse"),
    ("com.onecontext.mcp", "OneContext", "OneContext RAG-as-a-Service remote MCP server.", "https://onecontext.ai", "https://rag-mcp-2.whatsmcp.workers.dev/sse"),
    ("com.rube.mcp", "Rube", "Rube by Composio remote MCP server.", "https://composio.dev", "https://rube.app/mcp"),
    ("com.simplescraper.mcp", "Simplescraper", "Simplescraper web scraping remote MCP server.", "https://simplescraper.io", "https://mcp.simplescraper.io/mcp"),
    ("com.slack.mcp", "Slack", "Slack messaging remote MCP server.", "https://slack.com", "Slack remote MCP"),
    ("com.smartsheet.mcp", "Smartsheet", "Smartsheet work management remote MCP server.", "https://smartsheet.com", "Smartsheet remote MCP"),
    ("com.spotify.mcp", "Spotify", "Spotify music streaming remote MCP server.", "https://spotify.com", "Spotify remote MCP"),
    ("com.thoughtspot.mcp", "ThoughtSpot", "ThoughtSpot analytics remote MCP server.", "https://thoughtspot.com", "https://agent.thoughtspot.app/mcp"),
    ("com.uber.mcp", "Uber", "Uber ride-sharing remote MCP server.", "https://uber.com", "Uber remote MCP"),
    ("com.upwork.mcp", "Upwork", "Upwork freelance marketplace remote MCP server.", "https://upwork.com", "Upwork remote MCP"),
    ("com.vibemarketing.mcp", "VibeMarketing", "VibeMarketing social media remote MCP server.", "https://vibemarketing.ninja", "https://vibemarketing.ninja/mcp"),
    ("com.waystation.mcp", "WayStation", "WayStation productivity remote MCP server.", "https://waystation.ai", "https://waystation.ai/mcp"),
    ("com.webflow.mcp", "Webflow", "Webflow CMS remote MCP server.", "https://webflow.com", "https://mcp.webflow.com/sse"),
    ("com.wix.mcp", "Wix", "Wix website builder remote MCP server.", "https://wix.com", "https://mcp.wix.com/sse"),
    ("com.youtube.mcp", "YouTube", "YouTube video platform remote MCP server.", "https://youtube.com", "YouTube remote MCP"),
    ("com.zine.mcp", "Zine", "Zine memory remote MCP server.", "https://zine.ai", "https://www.zine.ai/mcp"),
    ("com.zoom.mcp", "Zoom", "Zoom video conferencing remote MCP server.", "https://zoom.us", "Zoom remote MCP"),
    ("com.atlassian.mcp", "Atlassian", "Atlassian Jira/Confluence remote MCP server.", "https://atlassian.com", "https://mcp.atlassian.com/v1/sse"),
    ("com.azure.devops", "Azure DevOps", "Azure DevOps remote MCP server (preview).", "https://azure.microsoft.com/devops", "Azure remote MCP"),
    ("com.buildkite.mcp", "Buildkite", "Buildkite CI/CD remote MCP server.", "https://buildkite.com", "https://mcp.buildkite.com/mcp"),
    ("com.cloudflare.bindings", "Cloudflare Workers", "Cloudflare Workers bindings remote MCP server.", "https://cloudflare.com", "https://bindings.mcp.cloudflare.com/sse"),
    ("com.cloudflare.observability", "Cloudflare Observability", "Cloudflare Observability remote MCP server.", "https://cloudflare.com", "https://observability.mcp.cloudflare.com/sse"),
    ("com.cloudinary.mcp", "Cloudinary", "Cloudinary asset management remote MCP server.", "https://cloudinary.com", "https://asset-management.mcp.cloudinary.com/sse"),
    ("com.grafbase.mcp", "Grafbase", "Grafbase GraphQL backend remote MCP server.", "https://grafbase.com", "https://api.grafbase.com/mcp"),
    ("com.github.mcp", "GitHub", "GitHub official remote MCP server.", "https://github.com", "https://api.githubcopilot.com/mcp"),
    ("com.globalping.mcp", "Globalping", "Globalping network tools remote MCP server.", "https://globalping.io", "https://mcp.globalping.dev/sse"),
    ("com.instantdb.mcp", "Instant", "InstantDB remote MCP server.", "https://instantdb.com", "https://mcp.instantdb.com/mcp"),
    ("com.neon.mcp", "Neon", "Neon serverless Postgres remote MCP server.", "https://neon.tech", "https://mcp.neon.tech/mcp"),
    ("com.netlify.mcp", "Netlify", "Netlify web hosting remote MCP server.", "https://netlify.com", "https://netlify-mcp.netlify.app/mcp"),
    ("com.newrelic.mcp", "New Relic", "New Relic observability remote MCP server.", "https://newrelic.com", "https://mcp.newrelic.com/mcp/"),
    ("com.portio.mcp", "Port IO", "Port IO developer portal remote MCP server.", "https://port.io", "https://mcp.port.io/v1"),
    ("com.prisma.mcp", "Prisma Postgres", "Prisma Postgres remote MCP server.", "https://prisma.io", "https://mcp.prisma.io/mcp"),
    ("com.sentry.mcp", "Sentry", "Sentry error tracking remote MCP server.", "https://sentry.io", "https://mcp.sentry.dev/sse"),
    ("com.stackoverflow.mcp", "Stack Overflow", "Stack Overflow remote MCP server.", "https://stackoverflow.com", "https://mcp.stackoverflow.com"),
    ("com.supabase.mcp", "Supabase", "Supabase Firebase alternative remote MCP server.", "https://supabase.com", "https://mcp.supabase.com/mcp"),
    ("com.vercel.mcp", "Vercel", "Vercel deployment platform remote MCP server.", "https://vercel.com", "https://mcp.vercel.com/"),
    ("com.attio.mcp", "Attio", "Attio CRM remote MCP server.", "https://attio.com", "https://mcp.attio.com/mcp"),
    ("com.close.mcp", "Close CRM", "Close CRM remote MCP server.", "https://close.com", "https://mcp.close.com/mcp"),
    ("com.hubspot.mcp", "HubSpot", "HubSpot CRM remote MCP server.", "https://hubspot.com", "https://app.hubspot.com/mcp/v1/http"),
    ("com.indeed.mcp", "Indeed", "Indeed job board remote MCP server.", "https://indeed.com", "https://mcp.indeed.com/claude/mcp"),
    ("com.microsoft.teams", "Microsoft Teams", "Microsoft Teams remote MCP server.", "https://teams.microsoft.com", "Teams remote MCP"),
    ("com.salesforce.mcp", "Salesforce", "Salesforce CRM remote MCP server.", "https://salesforce.com", "Salesforce remote MCP"),
    ("com.gusto.mcp", "Gusto", "Gusto payroll remote MCP server.", "https://gusto.com", "Gusto remote MCP"),
    ("com.mixpanel.mcp", "Mixpanel", "Mixpanel analytics remote MCP server.", "https://mixpanel.com", "Mixpanel remote MCP"),
    ("com.paypal.mcp", "PayPal", "PayPal payments remote MCP server.", "https://paypal.com", "https://mcp.paypal.com/sse"),
    ("com.plaid.mcp", "Plaid", "Plaid financial data remote MCP server.", "https://plaid.com", "https://api.dashboard.plaid.com/mcp/sse"),
    ("com.quickbooks.mcp", "QuickBooks", "QuickBooks accounting remote MCP server.", "https://quickbooks.intuit.com", "QuickBooks remote MCP"),
    ("com.ramp.mcp", "Ramp", "Ramp payments remote MCP server.", "https://ramp.com", "https://ramp-mcp-remote.ramp.com/mcp"),
    ("com.shopify.mcp", "Shopify", "Shopify e-commerce remote MCP server.", "https://shopify.com", "Shopify remote MCP"),
    ("com.square.mcp", "Square", "Square payments remote MCP server.", "https://square.com", "https://mcp.squareup.com/sse"),
    ("com.stripe.mcp", "Stripe", "Stripe payments remote MCP server.", "https://stripe.com", "https://mcp.stripe.com/"),
    ("com.ahrefs.mcp", "Ahrefs", "Ahrefs SEO platform remote MCP server.", "https://ahrefs.com", "Ahrefs remote MCP"),
    ("com.audioscrape.mcp", "Audioscrape", "Audioscrape RAG remote MCP server.", "https://audioscrape.com", "https://mcp.audioscrape.com"),
    ("com.dialer.mcp", "Dialer", "Dialer outbound calls remote MCP server.", "https://getdialer.app", "https://getdialer.app/sse"),
    ("com.ean-search.mcp", "EAN-Search", "EAN-Search product data remote MCP server.", "https://ean-search.org", "https://www.ean-search.org/mcp"),
    ("com.hiveintelligence.mcp", "Hive Intelligence", "Hive Intelligence crypto remote MCP server.", "https://hiveintelligence.xyz", "https://hiveintelligence.xyz/mcp"),
    ("com.invidio.mcp", "Invidio", "Invidio video remote MCP server.", "https://invideo.io", "https://mcp.invideo.io/sse"),
    ("com.morningstar.mcp", "MorningStar", "MorningStar data analysis remote MCP server.", "https://morningstar.com", "https://mcp.morningstar.com/mcp"),
    ("com.octagon.mcp", "Octagon", "Octagon market intelligence remote MCP server.", "https://octagonai.co", "https://mcp.octagonagents.com/mcp"),
    ("com.parallel.search", "Parallel Search", "Parallel web search remote MCP server.", "https://parallel.ai", "https://search-mcp.parallel.ai/mcp"),
    ("com.parallel.task", "Parallel Task", "Parallel web research remote MCP server.", "https://parallel.ai", "https://task-mcp.parallel.ai/mcp"),
    ("com.scorecard.mcp", "Scorecard", "Scorecard AI evaluation remote MCP server.", "https://scorecard.io", "https://scorecard-mcp.dare-d5b.workers.dev/sse"),
    ("com.snowflake.mcp", "Snowflake", "Snowflake data warehouse remote MCP server.", "https://snowflake.com", "Snowflake remote MCP"),
    ("com.stytch.mcp", "Stytch", "Stytch auth remote MCP server.", "https://stytch.com", "http://mcp.stytch.dev/mcp"),
    ("com.zenable.mcp", "Zenable", "Zenable security remote MCP server.", "https://zenable.io", "https://mcp.zenable.app/"),
    ("com.discord.mcp", "Discord", "Discord chat remote MCP server.", "https://discord.com", "Discord remote MCP"),
    ("com.pinterest.mcp", "Pinterest", "Pinterest visual discovery remote MCP server.", "https://pinterest.com", "Pinterest remote MCP"),
    ("com.resend.mcp", "Resend", "Resend email API remote MCP server.", "https://resend.com", "Resend remote MCP"),
    ("com.sendgrid.mcp", "SendGrid", "SendGrid email delivery remote MCP server.", "https://sendgrid.com", "SendGrid remote MCP"),
    ("com.twilio.mcp", "Twilio", "Twilio messaging remote MCP server.", "https://twilio.com", "Twilio remote MCP"),
    ("com.metro.mcp", "Metro MCP", "Metro transit remote MCP server.", "https://metro-mcp.anuragd.me", "https://metro-mcp.anuragd.me/sse"),
    ("com.turkishairlines.mcp", "Turkish Airlines", "Turkish Airlines remote MCP server.", "https://turkishtechlab.com", "https://mcp.turkishtechlab.com/mcp"),
    ("com.tweetsave.mcp", "TweetSave", "TweetSave social media remote MCP server.", "https://tweetsave.org", "https://mcp.tweetsave.org/sse"),
    ("com.xbird.mcp", "xbird", "xbird social media remote MCP server.", "https://github.com/checkra1neth/xbird-skill", "xbird remote MCP"),
]


def main():
    REGISTRY_ROOT.mkdir(exist_ok=True)
    count = 0
    skipped = 0
    for name, title, description, website, url in SERVERS:
        if "remote MCP" in url or url.startswith("Google ") or url.startswith("Azure ") or url.startswith("Teams "):
            skipped += 1
            continue

        parts = name.split(".")
        company = parts[1] if len(parts) > 1 else "unknown"
        server_slug = parts[-1] if len(parts) > 2 else company

        category_dir = REGISTRY_ROOT / company
        category_dir.mkdir(exist_ok=True)

        server_json = make_server(
            name=name,
            title=title,
            description=description,
            website=website,
            url=url
        )

        file_path = category_dir / f"{server_slug}.json"
        with open(file_path, "w") as f:
            json.dump(server_json, f, indent=2)
            f.write("\n")
        count += 1

    print(f"Generated {count} server.json files in {REGISTRY_ROOT}/")
    if skipped:
        print(f"Skipped {skipped} entries with placeholder URLs")


if __name__ == "__main__":
    main()
