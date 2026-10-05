"""Query converter utility for PostgreSQL parameter placeholders"""

def convert_sqlite_to_postgres_query(query):
    """Convert SQLite query with ? placeholders to PostgreSQL with %s placeholders."""
    if not query or '?' not in query:
        return query
    
    # Replace all ? with %s for psycopg2
    converted_query = query.replace('?', '%s')
    
    return converted_query