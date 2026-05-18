# Movensys Intelligence

## Setup repo
```
mkdir -p  ~/workspaces/
cd ~/workspaces/
git clone https://github.com/movensys/movensys-intelligence.git
```
## Example for Pick and Place
```
python3 movensys_sample/movensys_robopoly/pick_and_place.py red_cube GO true 2>&1 | tee baseline.log
grep '\[timing\]' baseline.log
```
