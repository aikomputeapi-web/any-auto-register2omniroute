# README Picture shows restoration design

## background
root directory `README.md` of“Interface preview”There are two image links that cannot be displayed properly.

The current writing is:
- `![Dashboard](./docs/images/dashboard.png null)`
- `![Global configuration / Plug-in management](./docs/images/settings-integrations.png null)`

The problem is that the link ends with `null`, this is not a standard Markdown Picture syntax can easily lead to GitHub,IDE Markdown Preview or other renderer parsing failed.

## Target
Without adjusting image resources or changing other README Under the premise of content, repair the root directory `README.md` There is a problem with the display of the two preview images.

## plan
Use minimal scope documentation fixes:

1. Only modify the root directory `README.md`
2. Change the two image links to standard Markdown grammar
3. At the same time, the path is unified to be more intuitive relative to the warehouse root directory. `docs/images/...`

Modified target writing:
- `![Dashboard](docs/images/dashboard.png)`
- `![Global configuration / Plug-in management](docs/images/settings-integrations.png)`

## Comparison of alternatives
### plan A: Delete only `null`
- Advantages: minimal changes
- Disadvantages: still retained `./docs/...`, the consistency is average

### plan B:delete `null` And unify the path writing method (recommended)
- Advantages: Fix display problems and standardize link writing at the same time
- Disadvantages: Than the plan A A little more text change, but no additional risk

## Scope of influence
- Modify file:`README.md`
- Does not involve:`docs/images/` Download image resources, front-end and back-end code, build process, and test logic

## Verification method
After repair, you should confirm:
1. `README.md` The link syntax between the two pictures is standard. Markdown
2. `docs/images/dashboard.png` and `docs/images/settings-integrations.png` path exists
3. exist GitHub style Markdown preview or local IDE In the preview, the two pictures can be displayed normally

## risk
The risk is extremely low. This time only the document link is fixed and does not affect the runtime code.