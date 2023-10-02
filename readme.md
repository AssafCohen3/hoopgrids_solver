# HoopGrids solver


## Download
[Windows](https://github.com/AssafCohen3/hoopgrids_solver/releases/latest/download/hoopgrids_solver.exe)

[Linux](https://github.com/AssafCohen3/hoopgrids_solver/releases/latest/download/hoopgrids_solver_amd64) - not valid anymore

## building in linux:

```bash
python3.9 -m venv env
source env/bin/activate
pip install -r requirements.txt
pip install pyinstaller
python3.9 -m PyInstaller --paths env/lib/python3.9/site-packages hoopgrids_solver.py --onefile
```

## Usage(linux example):
```bash
# solve the grid of Today
./hoopgrids_solver 
# solve the grid and optimize to find rarest players
./hoopgrids_solver -o yes
# solve the grid of specific date
./hoopgrids_solver -d "07-04-2023"
# solve only specific cells(0 and 8)
./hoopgrids_solver -c 0 -c 8
```
