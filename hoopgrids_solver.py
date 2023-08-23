import dataclasses
import datetime
import json
import logging
import re
import textwrap
import typing
from io import StringIO
from pathlib import Path

import click
import pyjson5
import requests
from bs4 import BeautifulSoup
from click_default_group import DefaultGroup

logging.basicConfig(level=logging.INFO)


@dataclasses.dataclass
class Challenge:
    c_type: str
    c_value: typing.Any

    def __post_init__(self):
        self.c_type = CHALLENGES_TYPES_ALIASES.get(self.c_type, self.c_type)


@dataclasses.dataclass
class PlayerAndVote:
    player: dict
    votes: typing.Optional[int] = None


@dataclasses.dataclass
class GridCell:
    pos: int
    challenge_1: Challenge
    challenge_2: Challenge
    valid_players: list[PlayerAndVote] = dataclasses.field(default_factory=list, init=False)
    total_votes: typing.Optional[int] = None


@dataclasses.dataclass
class Grid:
    grid_id: int
    vertical_challenges: list[Challenge]
    horizontal_challenges: list[Challenge]
    cells: list[GridCell]


SUPPORTED_CHALLENGES_TYPES = [
    'awards',
    'coach',
    'college',
    'stats',
    'teammate',
    'teams',
]

CHALLENGES_TYPES_ALIASES = {
    'awards_col2': 'awards',
    'stats_col2': 'stats'
}

MAIN_URL = 'https://www.hoopgrids.com'
PLAYER_VOTE_URL_TEMPLATE = 'https://hoop-grids-api-endpoint.vercel.app/api/getData?grid_id={grid_id}&grid_pos_id={grid_pos_id}&player_id={player_id}'
TOTAL_VOTES_URL_TEMPLATE = 'https://hoop-grids-api-endpoint.vercel.app/api/getTotal?grid_id={grid_id}&grid_pos_id={grid_pos_id}'

challenge_validation = {
    'awards': lambda player, c: len(player['awards'][c.c_value['id']]) > 0,
    'coach': lambda player, c: c.c_value['id'] in player['coaches'],
    'college': lambda player, c: c.c_value == player['college'],
    'stats': lambda player, c: len(player['stats'][c.c_value['id']]) > 0,
    'teammate': lambda player, c: c.c_value['id'] in player['teammates'],
    'teams': lambda player, c: c.c_value.upper() in player['teams']
}


def decode_js(js_object: str):
    return pyjson5.decode(js_object)


def fetch_main_script() -> str:
    resp = requests.get(MAIN_URL)
    soup = BeautifulSoup(resp.text, 'html.parser')
    main_element = soup.find_all('script', defer='defer')[0]
    main_script_url = MAIN_URL + main_element['src']
    main_script_resp = requests.get(main_script_url).text
    return main_script_resp


def build_grid_with_challenges_types(grid: dict, challenges_types_with_options: dict) -> Grid:
    possible_teams = challenges_types_with_options['teams']
    grid_teams = grid['teams']
    vertical = [
        Challenge('teams', possible_teams[grid_teams[0]]),
        Challenge('teams', possible_teams[grid_teams[1]]),
        None,
    ]
    col1_vertical = ['stats_col2', 'awards_col2']
    col2_vertical = ['stats', 'awards']
    vertical_keys = ['teams'] + col1_vertical + col2_vertical
    for key in col2_vertical:
        if key in grid:
            vertical[2] = Challenge(
                key,
                challenges_types_with_options[key][grid[key]]
            )

    for key in col1_vertical:
        if key in grid:
            vertical[1] = Challenge(
                key,
                challenges_types_with_options[key][grid[key]]
            )

    horizontal = [
        Challenge('teams', possible_teams[grid_teams[2]]),
        Challenge('teams', possible_teams[grid_teams[3]]),
        Challenge('teams', possible_teams[grid_teams[4]]),
    ]
    horizontal_keys = [key for key in challenges_types_with_options if key not in vertical_keys]
    for key in horizontal_keys:
        if key in grid:
            horizontal[2] = Challenge(
                key,
                challenges_types_with_options[key][grid[key]]
            )

    cells = []
    for row in range(3):
        for col in range(3):
            cells.append(
                GridCell(row * 3 + col, horizontal[row], vertical[col])
            )
    return Grid(
        grid['id'],
        vertical,
        horizontal,
        cells
    )


def fetch_players(main_script: str) -> list[dict[str, typing.Any]]:
    pattern = r"JSON.parse\('(\[[^;]*?\"first_name\"\s*:\s*\"Alaa.*?\])'"
    res = re.findall(pattern, main_script)[0]
    return decode_js(res)


def get_grids(main_script: str) -> list[dict[str, typing.Any]]:
    pattern = r"JSON.parse\('(\[[^;]*?\"date\"\s*:\s*\"Today\".*?\])'"
    res = re.findall(pattern, main_script)[0]
    return decode_js(res)


def get_challenges_types_with_options(main_script_text: str, types_with_var_name: dict[str, str]) -> dict[str, typing.Any]:
    types_with_options = {}
    for key, var in types_with_var_name.items():
        pattern = fr'{var}\s*=\s*(\[.*?\])'
        res = re.findall(pattern, main_script_text, re.MULTILINE | re.DOTALL)
        types_with_options[key] = decode_js(res[0])
    return types_with_options


def get_challenges_types_with_var_name(main_script: str, challenges_types: list[str]) -> dict[str, str]:
    types_with_var = {}
    for key in challenges_types:
        if key == 'teams':
            pattern = r's\.teams\.push\(([a-zA-Z_]+)\[e\]\)'
        else:
            pattern = fr'([a-zA-Z_]+)\s*\[\s*_\s*\.\s*{key}\s*\]'

        res = re.findall(pattern, main_script)
        types_with_var[key] = res[0]
    return types_with_var


def get_challenges_types(main_script_text: str) -> list[str]:
    pattern = r'var\s+s\s*=\s*(\{\s*id.*?\})'
    res = re.findall(pattern, main_script_text, re.MULTILINE | re.DOTALL)[0]
    res = res.replace('id:_.id,', '')
    types_dict = decode_js(res)
    return [
        key for key in types_dict if key != 'id'
    ]


def validate_player_and_challenges(player: dict, c1: Challenge, c2: Challenge) -> bool:
    if c1.c_type not in SUPPORTED_CHALLENGES_TYPES:
        raise Exception(f'Unsupported challenge type: {c1.c_type}')
    if c2.c_type not in SUPPORTED_CHALLENGES_TYPES:
        raise Exception(f'Unsupported challenge type: {c2.c_type}')
    c1, c2 = sorted([c1, c2], key=lambda c: c.c_type)
    if c1.c_type in ('awards', 'stats') and c2.c_type == 'teams':
        return c2.c_value.upper() in player[c1.c_type][c1.c_value['id']]
    return challenge_validation[c1.c_type](player, c1) and challenge_validation[c2.c_type](player, c2)


def solve_cell(cell: GridCell, players: list[dict]):
    valid_players = []
    for player in players:
        if validate_player_and_challenges(player, cell.challenge_1, cell.challenge_2):
            valid_players.append(PlayerAndVote(player))
    cell.valid_players = sorted(valid_players, key=lambda p: p.player['name'])


def solve_grid(grid: Grid, players: list[dict], cells_to_solve: typing.Optional[list[int]] = None):
    if cells_to_solve is None:
        cells_to_solve = list(range(len(grid.cells)))
    for cell_index in cells_to_solve:
        solve_cell(grid.cells[cell_index], players)


def create_grid(grids_dicts: list[dict], grid_date: str, challenges_types_with_options: dict) -> typing.Optional[Grid]:
    grid_dict = [grid_dict for grid_dict in grids_dicts if grid_dict['date'] == grid_date]
    if len(grid_dict) == 0:
        return None
    grid_dict = grid_dict[0]
    return build_grid_with_challenges_types(grid_dict, challenges_types_with_options)


def format_player_line(player: PlayerAndVote, cell: GridCell) -> str:
    if player.votes is not None and cell.total_votes is not None:
        return f'{player.player["name"]}: {player.votes / cell.total_votes}'
    return f'{player.player["name"]}'


def optimize_grid(grid: Grid, cells_to_optimize: typing.Optional[list[int]] = None):
    if cells_to_optimize is None:
        cells_to_optimize = list(range(len(grid.cells)))
    for cell_index in cells_to_optimize:
        cell = grid.cells[cell_index]
        optimize_cell(grid, cell)
        print(f'for cell {cell.pos}:')
        top_ten_players_lines = [
            format_player_line(player, cell)
            for player in cell.valid_players[:10]
        ]
        for player_line in top_ten_players_lines:
            print(textwrap.indent(player_line, ' ' * 4))
        print('*********')


def optimize_cell(grid: Grid, grid_cell: GridCell):
    print(f'optimizing cell {grid_cell.pos}...')
    for valid_player in grid_cell.valid_players:
        votes_url = PLAYER_VOTE_URL_TEMPLATE.format(grid_id=grid.grid_id, grid_pos_id=grid_cell.pos,
                                                    player_id=valid_player.player['id'])
        resp = requests.get(votes_url)
        resp = json.loads(resp.text)
        valid_player.votes = resp['data']['votes']
        logging.info(f'{valid_player.player["name"]} got {valid_player.votes}')
    total_votes_url = TOTAL_VOTES_URL_TEMPLATE.format(grid_id=grid.grid_id, grid_pos_id=grid_cell.pos)
    resp = requests.get(total_votes_url)
    resp = json.loads(resp.text)
    grid_cell.total_votes = resp['data']['votes']
    grid_cell.valid_players = sorted(grid_cell.valid_players, key=lambda p: p.votes)


def output_grid_solution(grid: Grid):
    file_path = Path(f'./grid_{grid.grid_id}_solved.txt')
    logging.info(f'writing results to {file_path.absolute()}...')
    data = StringIO()
    for cell in grid.cells:
        data.write(f'cell {cell.pos}:\n')
        for valid_player in cell.valid_players:
            player_line = format_player_line(valid_player, cell)
            data.write(textwrap.indent(player_line, ' ' * 4) + '\n')
        data.write('\n****************\n\n')
    with open(file_path, 'w') as f:
        f.write(data.getvalue())


def main(optimize: bool, grid_date: str, cells: typing.Optional[list[int]] = None):
    logging.info('fetching main script...')
    main_script_text = fetch_main_script()
    logging.info('fetching players...')
    players = fetch_players(main_script_text)
    logging.info(f'fetched {len(players)} players')
    logging.info('fetching challenges types...')
    challenges_types = get_challenges_types(main_script_text)
    logging.info(f'found the following challenges types: {challenges_types}')
    challenges_types_with_var_name = get_challenges_types_with_var_name(main_script_text, challenges_types)
    logging.info('fetching challenges options...')
    challenges_types_with_options = get_challenges_types_with_options(main_script_text, challenges_types_with_var_name)
    logging.info('fetching grids...')
    grids = get_grids(main_script_text)
    grid = create_grid(grids, grid_date, challenges_types_with_options)
    if grid is None:
        logging.info(f'could not found requested grid for date {grid_date}')
        return
    solve_grid(grid, players, cells)
    if optimize:
        print('\n\n\n')
        print('$$$$$$$$')
        print('\n\n\n')
        optimize_grid(grid, cells)
    output_grid_solution(grid)


@click.group(cls=DefaultGroup, default='solve-grid-cmd', default_if_no_args=True)
def cli():
    pass


@cli.command()
@click.option('--optimize', '-o', type=click.Choice(['yes', 'no'], case_sensitive=False),
              prompt='Optimize and search for rarest players(may take some minutes)?')
@click.option('--grid_date', '-d', prompt='Which date to solve?(leave empty for today)', default='')
@click.option('--cell', '-c', type=int, multiple=True)
def solve_grid_cmd(optimize: str, grid_date: str, cell: list[int]):
    if grid_date.strip() == '':
        grid_date = 'Today'
    optimize = optimize.lower() == 'yes'
    main(optimize, grid_date, cell)


@cli.command()
def test():
    current_date = datetime.date(2023, 7, 4)
    while current_date != datetime.date.today():
        formatted_date = current_date.strftime('%m-%d-%Y')
        main(False, formatted_date)
        current_date += datetime.timedelta(days=1)


if __name__ == '__main__':
    cli()
