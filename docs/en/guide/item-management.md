# Item Management

## Add by DOI

```bash
zot add --doi "10.1038/s41586-023-06139-9"
```

## Add by URL

```bash
zot add --url "https://arxiv.org/abs/2301.00001"
```

## Add from Local PDF

```bash
zot add --pdf paper.pdf
```

Extracts DOI from the PDF, creates the item, and attaches the file.

## Batch Import

```bash
zot add --from-file dois.txt
```

The file should contain one DOI or URL per line.

## Update Metadata

```bash
zot update ABC123 --title "Corrected Title"
zot update ABC123 --date "2024-01-15"
zot update ABC123 --field publicationTitle="Nature"
zot --detail full summarize-all --exclude-tag update/metadata --limit 100
zot update --from-jsonl cleaned-metadata.jsonl --add-tag update/metadata
```

For AI-assisted metadata cleanup, first export writable metadata with `zot --detail full summarize-all`, then write back one JSON object per line:

```json
{"key":"ABC123","fields":{"title":"Clean title","abstractNote":"Clean abstract"}}
```

## Delete Items

```bash
zot delete ABC123                 # Confirmation prompt
zot delete ABC123 --yes           # Skip confirmation
zot --no-interaction delete ABC123  # Script mode
```

Items are moved to Zotero's trash, not permanently deleted.

## Trash Management

```bash
zot trash list                    # View trashed items
zot trash restore ABC123          # Restore from trash
```

## Upload Attachments

```bash
zot attach ABC123 --file supplementary.pdf
```

## Find Duplicates

```bash
zot duplicates                         # Both DOI and title matching
zot duplicates --by doi                # DOI only
zot duplicates --by title              # Fuzzy title only
zot duplicates --threshold 0.9         # Stricter matching
```
