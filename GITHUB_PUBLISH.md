# Publish Oxford Move to your GitHub account

The source code is ready. These steps must be performed while signed in to **your own** GitHub account.

## Easiest: GitHub Desktop

1. Extract the `oxford-bus-planner.zip` archive and open **GitHub Desktop** (https://desktop.github.com/).
2. Select **File → Add local repository**, browse to the extracted `oxford-bus-planner` folder.
3. If prompted that the directory is not a Git repository, choose **Create a repository here**. Use name `oxford-bus-planner` and include the existing README (do not overwrite it).
4. Review the files, write a commit message such as `Initial working version: Oxford bus route planner`, and **Commit to main**.
5. Select **Publish repository**, set the name to `oxford-bus-planner`, and **uncheck "Keep this code private"** if you want recruiters to see it.
6. Confirm publication; your URL will look like `https://github.com/YOUR_USERNAME/oxford-bus-planner`.

## Alternative: Git in the VS Code terminal

Create an **empty** *public* repository called `oxford-bus-planner` in GitHub. Do **not** ask GitHub to initialize a README, `.gitignore` or licence; those files are already included in this project. Then, in the extracted source folder, run:

```powershell
git init
git branch -M main
git add .
git commit -m "Initial release: Oxford bus journey planner"
git remote add origin https://github.com/YOUR_USERNAME/oxford-bus-planner.git
git push -u origin main
```

Replace `YOUR_USERNAME` with your username. You may have to sign in via Git Credential Manager or authenticate through a browser.

## Recommended repository settings

- **Description:** An Oxford bus journey planner built with Python, Flask, SQLite, GTFS and a timetable-based earliest-arrival routing algorithm.
- **Topics:** `python`, `flask`, `gtfs`, `public-transport`, `route-planning`, `graph-algorithms`, `sqlite`, `javascript`, `leaflet`
- **About → Website:** Add a working deployment URL only once the app has actually been deployed.
- **Actions:** Check that the `Python tests` workflow passes after pushing.

**Important:** The demo file is **synthetic**; genuine Oxford bus route information requires the live operator GTFS download. Before discussing this project in an interview, run through the code and make sure you can explain the GTFS import, time-dependent connection scan and the limitations of estimated pedestrian routes.
