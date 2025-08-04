# LinkedIn Parser with BeautifulSoup

This project provides a BeautifulSoup-based parser for LinkedIn to search and extract candidate information. The parser includes both basic and enhanced versions with different features.

## Features

- **Search candidates** by keywords, location, and other filters
- **Extract candidate details** including name, headline, location, company
- **Get detailed profiles** with experience, education, and about sections
- **Rate limiting** to respect LinkedIn's terms of service
- **Multiple selector strategies** to handle LinkedIn's dynamic structure
- **Authentication support** for full functionality

## Installation

1. Install the required dependencies:
```bash
pip install -r requirements.txt
```

## Usage

### Basic Usage (Without Login)

```python
from linkedin_parser import LinkedInParser

# Initialize parser
parser = LinkedInParser()

# Search for candidates
candidates = parser.search_candidates(
    keywords="software engineer",
    location="San Francisco",
    limit=5
)

# Print results
for candidate in candidates:
    print(f"Name: {candidate.name}")
    print(f"Title: {candidate.headline}")
    print(f"Location: {candidate.location}")
    print(f"Company: {candidate.company}")
    print(f"Profile: {candidate.profile_url}")
    print("---")
```

### Enhanced Usage (With Login)

```python
from linkedin_parser_enhanced import LinkedInParser

# Initialize parser with credentials
parser = LinkedInParser(
    email="your_email@example.com",
    password="your_password"
)

# Login to LinkedIn
if parser.login():
    print("Successfully logged in")
    
    # Search for candidates
    candidates = parser.search_candidates(
        keywords="product manager",
        location="New York",
        limit=10
    )
    
    # Get detailed information for first candidate
    if candidates:
        details = parser.get_candidate_details(candidates[0].profile_url)
        if details:
            print(f"Detailed profile: {details}")
else:
    print("Login failed")
```

## Files

- `linkedin_parser.py` - Basic parser with simple functionality
- `linkedin_parser_enhanced.py` - Enhanced parser with authentication and detailed profile extraction
- `requirements.txt` - Required Python packages

## Important Notes

### LinkedIn's Anti-Scraping Measures

LinkedIn has strict anti-scraping measures in place:

1. **Authentication Required**: Most functionality requires a LinkedIn account
2. **Rate Limiting**: Respect delays between requests (2-3 seconds)
3. **Dynamic Content**: LinkedIn uses JavaScript to load content dynamically
4. **CAPTCHA Protection**: May encounter CAPTCHA challenges
5. **Terms of Service**: Ensure compliance with LinkedIn's ToS

### Legal Considerations

- **Terms of Service**: Review LinkedIn's Terms of Service before use
- **Rate Limiting**: Implement appropriate delays between requests
- **Data Usage**: Ensure compliance with data protection regulations
- **Personal Use**: This tool is for educational/personal use only

### Limitations

- **Authentication Required**: Full functionality requires LinkedIn login
- **Dynamic Content**: Some content may not be accessible without JavaScript
- **Structure Changes**: LinkedIn frequently updates their HTML structure
- **Anti-Bot Measures**: May encounter blocking or CAPTCHA challenges

## Error Handling

The parser includes comprehensive error handling:

```python
try:
    candidates = parser.search_candidates("software engineer")
    print(f"Found {len(candidates)} candidates")
except Exception as e:
    print(f"Error: {e}")
```

## Customization

### Adding New Selectors

LinkedIn's structure changes frequently. To add new selectors:

```python
# In _extract_candidate_info method
name_selectors = [
    'span.entity-result__title-text',
    'h3.search-result__title',
    'a.search-result__result-link',
    'your-new-selector'  # Add new selectors here
]
```

### Rate Limiting

Adjust the delay between requests:

```python
# In search_candidates method
time.sleep(2)  # Increase for more conservative rate limiting
```

## Example Output

```
Found 5 candidates:

1. John Doe
   Title: Senior Software Engineer at Tech Corp
   Location: San Francisco, CA
   Company: Tech Corp
   Profile: https://www.linkedin.com/in/johndoe

2. Jane Smith
   Title: Full Stack Developer
   Location: San Francisco Bay Area
   Company: Startup Inc
   Profile: https://www.linkedin.com/in/janesmith
```

## Troubleshooting

### Common Issues

1. **No results found**: LinkedIn may have changed their HTML structure
2. **Login failed**: Check credentials and LinkedIn's security settings
3. **Blocked requests**: Implement longer delays between requests
4. **CAPTCHA challenges**: Consider using a browser automation tool

### Debug Mode

Enable debug logging:

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

## Contributing

When contributing to this project:

1. Test with different LinkedIn page structures
2. Update selectors as LinkedIn changes their HTML
3. Respect rate limits and LinkedIn's terms of service
4. Add comprehensive error handling

## License

This project is for educational purposes only. Please ensure compliance with LinkedIn's Terms of Service and applicable data protection regulations.
