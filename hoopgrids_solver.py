from dataclasses import dataclass, field
import datetime
import json
import re
import requests
from typing import Any

import click
import unidecode


SITE_URL = 'https://hoopgrids.com'
FIRST_GRID_DATE = datetime.datetime(2023, 7, 4)


@dataclass
class PlayerData:
	player_id: str
	name: str


@dataclass 
class PlayerDataWithVotes:
	player_data: PlayerData
	votes: int


@dataclass
class Cell:
	cell_code: str
	valid_players: list[PlayerData] = field(default_factory=list)
	players_votes: list[PlayerDataWithVotes] = field(default_factory=list)


@dataclass
class Grid:
	cells: list[Cell]


def fetch_main_script() -> str:
	print('fetching main script...')
	main_site_resp = requests.get(SITE_URL).text
	script_pattern = r'<script src="(main\..*?\.js)"'
	script_name = re.findall(script_pattern, main_site_resp)[0]
	main_script = requests.get(f'{SITE_URL}/{script_name}').text
	return main_script


def fetch_players(main_script: str) -> dict[str, PlayerData]:
	print('fetching players...')
	player_pattern = r'\{\s*id:\s*((\d+)(?:e(\d+))?),\s*name:\s*"(.*?)"'
	players_matches = re.findall(player_pattern, main_script)
	players = {}
	for player_full_id, id_before_e, id_after_e, player_name in players_matches:
		if id_after_e != '':
			player_full_id = str(int(id_before_e) * (10 ** int(id_after_e)))
		int(player_full_id)
		player_name = player_name.encode().decode('unicode-escape')
		player_name = unidecode.unidecode(player_name)
		players[player_full_id] = PlayerData(player_full_id, player_name)
	return players


def get_date_code(date_str: str) -> int:
	d = datetime.datetime.strptime(date_str, '%d-%m-%Y')
	return (d - FIRST_GRID_DATE).days


def get_cell_votes(day_code: int, players: dict[str, PlayerData], cell_code: str) -> list[PlayerDataWithVotes]:
	print(f'fetching cell {cell_code} votes...')
	votes_url = f'https://api.hoopgrids.com/gamestat/{day_code+2}/playerselection/{cell_code}'
	resp = requests.get(votes_url).text
	votes = json.loads(json.loads(resp)['playerCounts'])
	to_ret = []
	for player_id, votes in votes:
		to_ret.append(PlayerDataWithVotes(players[player_id], votes))
	return to_ret


def complete_players_without_votes(valid_players: list[PlayerData], voted_players: list[PlayerDataWithVotes]) -> list[PlayerDataWithVotes]:
	voted_players_set = {
		p.player_data.player_id
		for p in voted_players
	}
	to_ret = []
	for p in valid_players:
		if p.player_id not in voted_players_set:
			to_ret.append(PlayerDataWithVotes(p, 0))
	return to_ret


def get_cell(day_code: int, row: int, col: int, 
		grid_data: dict[str, Any], players: dict[str, PlayerData]) -> Cell:
	cell_code = f'{row}-{col}'
	print(f'fetching cell {cell_code}...')
	cell_players = grid_data[cell_code]['players']
	cell_players = [
		players[p_id]
		for p_id in cell_players
	]
	cell_votes = get_cell_votes(day_code, players, cell_code)
	cell_votes.extend(complete_players_without_votes(cell_players, cell_votes))
	cell_votes = sorted(cell_votes, key=lambda p: (p.votes, p.player_data.name))
	return Cell(cell_code, cell_players, cell_votes)


def get_grid(day_code: int, players: dict[str, PlayerData]) -> Grid:
	print(f'building the grid for day {day_code}...')
	grid_url = f'https://api.hoopgrids.com/game/{day_code}'
	resp = requests.get(grid_url).text
	grid_data = json.loads(resp)
	grid_cells = []
	for row in range(0, 3):
		for col in range(0, 3):
			grid_cells.append(get_cell(day_code, row, col, grid_data, players))
	return Grid(grid_cells)


def display_grid(grid_date: str, grid: Grid) -> str:
	valid_players_str = ''
	sorted_players_votes_str = ''
	for cell in grid.cells:
		valid_players_names = [p.name for p in cell.valid_players]
		valid_players_str += f'Cell {cell.cell_code}:\n\n'
		valid_players_str += '\n'.join(valid_players_names)
		valid_players_str += '\n\n*******************\n\n'
		players_with_votes_names = [
			f'{p.player_data.name} - {p.votes}'
			for p in cell.players_votes
		]
		sorted_players_votes_str += f'Cell {cell.cell_code}:\n\n'
		sorted_players_votes_str += '\n'.join(players_with_votes_names)
		sorted_players_votes_str += '\n\n*******************\n\n'
	to_ret = f'Results for {grid_date}:\n\n{valid_players_str}$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$\n\nSorted by votes: \n\n{sorted_players_votes_str}'
	return to_ret


@click.command()
@click.argument('grid_date', required=False, default='Today')
def main(grid_date: str):
	if grid_date.lower() == 'today':
		current_grid_date = datetime.datetime.now() - datetime.timedelta(days=1)
		grid_date = current_grid_date.strftime('%d-%m-%Y')
	print(f'requested grid date: {grid_date}.')
	day_code = get_date_code(grid_date)
	print(f'requested grid date code: {day_code}.')
	main_script = fetch_main_script()
	players = fetch_players(main_script)
	grid = get_grid(day_code, players)
	output = display_grid(grid_date, grid)
	output_file_name = f'hoopgrids_solved_{grid_date}.txt'
	with open(output_file_name, 'w') as f:
		f.write(output)
	print(f'Written results to {output_file_name}')


if __name__ == '__main__':
	main()
