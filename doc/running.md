# Setup movensys manipulator
https://github.com/movensys/movensys-manipulator/tree/main/doc
especially 1, 2, and 4

# Setup repo
```
mkdir -p  ~/workspaces/
cd ~/workspaces/
git clone git@bitbucket.org:mvs_app/movensys_vlm_manipulator.git
```

# Setup docker
```
cd ~/workspaces/movensys_vlm_manipulator/movensys_vlm_fastapi
docker compose down 
docker compose build 
docker compose up
```

# Running
open `localhost:8000`

# Check API
open `localhost:8000/docs`