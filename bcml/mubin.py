# Copyright 2019 Nicene Nerd <macadamiadaze@gmail.com>
# Licensed under GPLv3+
import shutil
from collections import namedtuple
from copy import deepcopy
from functools import partial
from multiprocessing import Pool, cpu_count
from pathlib import Path
from typing import Union, List

import byml
import rstb
import rstb.util
import sarc
import wszst_yaz0
import yaml
from byml import yaml_util

from bcml import util

Map = namedtuple('Map', 'section type')


def consolidate_map_files(modded_maps: List[str]) -> List[Map]:
    """ Turns a list of modified .mubin files into a list of modified map sections and types """
    return list(dict.fromkeys(map(lambda path: Map(*(Path(path).stem.split('_'))), modded_maps)))


def get_stock_map(map: Union[Map, tuple]) -> dict:
    """
    Finds the most significant available map unit from the unmodded game and returns its
    contents as a dict.

    :param map: The map section and type.
    :type map: :class:`bcml.mubin.Map`
    :return: Returns a dict representation of the requested map unit.
    :rtype: dict
    """
    if isinstance(map, tuple):
        map = Map(*map)
    aoc_dir = util.get_aoc_dir()
    map_bytes = None
    if (aoc_dir / 'Pack' / 'AocMainField.pack').exists():
        with (aoc_dir / 'Pack' / 'AocMainField.pack').open('rb') as sf:
            map_pack = sarc.read_file_and_make_sarc(sf)
        if map_pack:
            try:
                map_bytes = map_pack.get_file_data(
                    f'Map/MainField/{map.section}/{map.section}_{map.type}.smubin')
            except KeyError:
                map_bytes = None
    if not map_bytes:
        if (aoc_dir / 'Map' / 'MainField' / map.section / f'{map.section}_{map.type}.smubin').exists():
            map_bytes = (aoc_dir / 'Map' / 'MainField' /
                         map.section / f'{map.section}_{map.type}.smubin').read_bytes()
        elif (util.get_game_dir() / 'content' / 'Map' / 'MainField' / map.section / f'{map.section}_{map.type}.smubin').exists():
            map_bytes = (util.get_game_dir() / 'content' / 'Map' / 'MainField' /
                         map.section / f'{map.section}_{map.type}.smubin').read_bytes()
    map_bytes = wszst_yaz0.decompress(map_bytes)
    return byml.Byml(map_bytes).parse()


def get_modded_map(map: Union[Map, tuple], tmp_dir: Path) -> dict:
    """
    Finds the most significant available map unit in a mod for a given section and type
    and returns its contents as a dict. Checks `AocMainField.pack` first, then the unpacked
    aoc map files, and then the base game map files.

    :param map: The map section and type.
    :type map: :class:`bcml.mubin.Map`
    :param tmp_dir: The path to the base directory of the mod.
    :type tmp_dir: :class:`pathlib.Path`
    :return: Returns a dict representation of the requested map unit.
    :rtype: dict
    """
    if isinstance(map, tuple):
        map = Map(*map)
    map_bytes = None
    if (tmp_dir / 'aoc' / '0010' / 'Pack' / 'AocMainField.pack').exists():
        with (tmp_dir / 'aoc' / '0010' / 'Pack' / 'AocMainField.pack').open('rb') as sf:
            map_pack = sarc.read_file_and_make_sarc(sf)
        if map_pack:
            try:
                map_bytes = map_pack.get_file_data(
                    f'Map/MainField/{map.section}/{map.section}_{map.type}.smubin')
            except KeyError:
                pass
    if not map_bytes:
        if (tmp_dir / 'aoc' / '0010' / 'Map' / 'MainField' / map.section / f'{map.section}_{map.type}.smubin').exists():
            map_bytes = (tmp_dir / 'aoc' / '0010' / 'Map' / 'MainField' /
                         map.section / f'{map.section}_{map.type}.smubin').read_bytes()
        elif (tmp_dir / 'content' / 'Map' / 'MainField' / map.section / f'{map.section}_{map.type}.smubin').exists():
            map_bytes = (tmp_dir / 'content' / 'Map' / 'MainField' /
                         map.section / f'{map.section}_{map.type}.smubin').read_bytes()
    map_bytes = wszst_yaz0.decompress(map_bytes)
    return byml.Byml(map_bytes).parse()


def get_map_diff(base_map: Union[dict, Map], mod_map: dict) -> dict:
    """
    Detects the changes made to a modded map unit.

    :param base_map: The contents or identity of the map unit from the base game to compare from.
    :type base_map: Union[dict, :class:`bcml.mubin.Map`]
    :param mod_map: The contents of the modded map unit.
    :type mod_map: dict
    :return: Returns a dict of changes in the modded map unit, including added, modified, and deleted actors.
    :rtype: dict of str: list
    """
    diffs = {
        'add': [],
        'mod': {},
        'del': []
    }
    if isinstance(base_map, Map):
        base_map = get_stock_map(base_map)
    base_hashes = [obj['HashId'] for obj in base_map['Objs']]
    mod_hashes = [obj['HashId'] for obj in mod_map['Objs']]
    for obj in mod_map['Objs']:
        if obj['HashId'] not in base_hashes:
            diffs['add'].append(obj)
        elif obj['HashId'] in base_hashes and obj != base_map['Objs'][base_hashes.index(obj['HashId'])]:
            diffs['mod'][obj['HashId']] = deepcopy(obj)
    diffs['del'] = list(set(base_hashes) - set(mod_hashes))
    return diffs


def get_all_map_diffs() -> dict:
    """
    Consolidates diffs for installed map unit mods into a single set of additions, modifications, and deletions.

    :return: Returns a dict of modded map units with their added, modified, and deleted actors.
    :rtype: dict of str: dict
    """
    diffs = {}
    loader = yaml.CSafeLoader
    yaml_util.add_constructors(loader)
    for mod in util.get_installed_mods():
        if (mod.path / 'logs' / 'map.yml').exists():
            with (mod.path / 'logs' / 'map.yml').open('r') as yf:
                map_yml = yaml.load(yf, Loader=loader)
            for file, diff in map_yml.items():
                a_map = Map(*file.split('_'))
                if a_map not in diffs:
                    diffs[a_map] = []
                diffs[a_map].append(diff)
    c_diffs = {}
    for file, mods in list(diffs.items()):
        c_diffs[file] = {
            'add': [],
            'mod': {},
            'del': list(dict.fromkeys([hash_id for hashes in [mod['del'] for mod in mods] for hash_id in hashes]))
        }
        for mod in mods:
            for hash_id, actor in mod['mod'].items():
                c_diffs[file]['mod'][hash_id] = deepcopy(actor)
        mods.reverse()
        add_hashes = []
        for mod in mods:
            for actor in mod['add']:
                if actor['HashId'] not in add_hashes:
                    add_hashes.append(actor['HashId'])
                    c_diffs[file]['add'].append(actor)
    return c_diffs


def log_modded_texts(tmp_dir: Path, modded_mubins: List[str]):
    diffs = {}
    modded_maps = consolidate_map_files(modded_mubins)
    for modded_map in modded_maps:
        diffs['_'.join(modded_map)] = get_map_diff(
            modded_map, get_modded_map(modded_map, tmp_dir))
    log_file: Path = tmp_dir / 'logs' / 'map.yml'
    log_file.parent.mkdir(parents=True, exist_ok=True)
    dumper = yaml.CSafeDumper
    yaml_util.add_representers(dumper)
    with log_file.open('w') as lf:
        yaml.dump(diffs, lf, Dumper=dumper)


def merge_map(map_pair: tuple, rstb_calc: rstb.SizeCalculator, verbose: bool = False):
    map_unit, changes = map_pair
    if verbose:
        print(
            f'Merging {len(changes)} versions of {"_".join(map_unit)}...')
    merge_map = get_stock_map(map_unit)
    stock_hashes = [obj['HashId'] for obj in merge_map['Objs']]
    mods = changes['mod'].items()
    for hash_id, actor in changes['mod'].items():
        merge_map['Objs'][stock_hashes.index(hash_id)] = deepcopy(actor)
    stock_links = []
    if map_unit.type == 'Static' and len(changes['del']) > 0:
        for actor in merge_map['Objs']:
            if 'LinksToObj' in actor:
                stock_links.extend([link['DestUnitHashId']
                                    for link in actor['LinksToObj']])
    for map_del in changes['del']:
        if map_del in stock_hashes and map_del not in stock_links:
            merge_map['Objs'].pop(stock_hashes.index(map_del))
    merge_map['Objs'].extend(
        [change for change in changes['add'] if change['HashId'] not in stock_hashes])
    merge_map['Objs'].sort(key=lambda actor: actor['HashId'])

    aoc_out: Path = util.get_master_modpack_dir() / 'aoc' / '0010' / 'Map' / \
        'MainField' / map_unit.section / \
        f'{map_unit.section}_{map_unit.type}.smubin'
    aoc_out.parent.mkdir(parents=True, exist_ok=True)
    aoc_bytes = byml.Writer(merge_map, be=True).get_bytes()
    aoc_out.write_bytes(wszst_yaz0.compress(aoc_bytes))
    merge_map['Objs'] = [obj for obj in merge_map['Objs']
                         if not obj['UnitConfigName'].startswith('DLC')]
    (util.get_master_modpack_dir() / 'content' / 'Map' /
     'MainField' / map_unit.section).mkdir(parents=True, exist_ok=True)
    base_out = util.get_master_modpack_dir() / 'content' / 'Map' / 'MainField' / \
        map_unit.section / f'{map_unit.section}_{map_unit.type}.smubin'
    base_out.parent.mkdir(parents=True, exist_ok=True)
    base_bytes = byml.Writer(merge_map, be=True).get_bytes()
    base_out.write_bytes(wszst_yaz0.compress(base_bytes))
    return {
        'aoc': (f'Aoc/0010/Map/MainField/{map_unit.section}/{map_unit.section}_{map_unit.type}.mubin', rstb_calc.calculate_file_size_with_ext(aoc_bytes, True, '.mubin')),
        'main': (f'Map/MainField/{map_unit.section}/{map_unit.section}_{map_unit.type}.mubin', rstb_calc.calculate_file_size_with_ext(base_bytes, True, '.mubin'))
    }


def merge_maps(verbose: bool = False):
    aoc_pack = util.get_master_modpack_dir() / 'aoc' / '0010' / \
        'Pack' / 'AocMainField.pack'
    if not aoc_pack.exists() or aoc_pack.stat().st_size > 0:
        print('Emptying AocMainField.pack...')
        aoc_pack.parent.mkdir(parents=True, exist_ok=True)
        aoc_pack.write_bytes(b'')
    shutil.rmtree(str(util.get_master_modpack_dir() /
                      'aoc' / '0010' / 'Map' / 'MainField'), ignore_errors=True)
    shutil.rmtree(str(util.get_master_modpack_dir() /
                      'content' / 'Map' / 'MainField'), ignore_errors=True)
    log_path = util.get_master_modpack_dir() / 'logs' / 'map.log'
    if log_path.exists():
        log_path.unlink()
    print('Loading map mods...')
    map_diffs = get_all_map_diffs()
    if len(map_diffs) == 0:
        print('No map merge necessary')
        return

    rstb_vals = {}
    rstb_calc = rstb.SizeCalculator()
    print('Merging modded map units...')
    num_threads = min(cpu_count() - 1, len(map_diffs))
    p = Pool(processes=num_threads)
    rstb_results = p.map(partial(merge_map, rstb_calc=rstb_calc,
                                 verbose=verbose), list(map_diffs.items()))
    p.close()
    p.join()
    for result in rstb_results:
        rstb_vals[result['aoc'][0]] = result['aoc'][1]
        rstb_vals[result['main'][0]] = result['main'][1]

    print('Adjusting RSTB...')
    with log_path.open('w') as lf:
        for canon, val in rstb_vals.items():
            lf.write(f'{canon},{val}\n')
    print('Map merge complete')


def get_dungeonstatic_diff(file: Path) -> dict:
    """Returns the changes made to the Static.smubin containing shrine entrance coordinates

    :param file: The Static.mubin file to diff
    :type file: :class:`pathlib.Path`
    :return: Returns a dict of shrines and their updated entrance coordinates
    :rtype: dict of str: dict
    """
    base_file = util.get_game_file(
        'aoc/0010/Map/CDungeon/Static.smubin', aoc=True)
    base_pos = byml.Byml(
        wszst_yaz0.decompress_file(str(base_file))
    ).parse()['StartPos']

    mod_pos = byml.Byml(
        wszst_yaz0.decompress_file(str(file))
    ).parse()['StartPos']

    base_dungeons = [dungeon['Map'] for dungeon in base_pos]
    diffs = {}
    for dungeon in mod_pos:
        if dungeon['Map'] not in base_dungeons:
            diffs[dungeon['Map']] = dungeon
        else:
            base_dungeon = base_pos[base_dungeons.index(dungeon['Map'])]
            if dungeon['Rotate'] != base_dungeon['Rotate']:
                diffs[dungeon['Map']] = {
                    'Rotate': dungeon['Rotate']
                }
            if dungeon['Translate'] != base_dungeon['Translate']:
                if dungeon['Map'] not in diffs:
                    diffs[dungeon['Map']] = {}
                diffs[dungeon['Map']]['Translate'] = dungeon['Translate']

    return diffs


def merge_dungeonstatic(verbose: bool = False):
    """
    Merges all changes to the CDungeon Static.smubin

    :param verbose: Whether to display more detailed output, defaults to False
    :type verbose: bool, optional
    """
    diffs = {}
    loader = yaml.CSafeLoader
    yaml_util.add_constructors(loader)
    for mod in [mod for mod in util.get_installed_mods() if (mod.path / 'logs' / 'dstatic.yml').exists()]:
        diffs.update(
            yaml.load(
                (mod.path / 'logs' / 'dstatic.yml').read_bytes(),
                Loader=loader
            )
        )

    if len(diffs) == 0:
        return

    new_static = byml.Byml(
        wszst_yaz0.decompress_file(
            str(util.get_game_file('aoc/0010/Map/CDungeon/Static.smubin'))
        )
    ).parse()

    base_dungeons = [dungeon['Map'] for dungeon in new_static['StartPos']]
    for dungeon, diff in diffs.items():
        if dungeon not in base_dungeons:
            new_static['StartPos'].append(diff)
        else:
            for key, value in diff.items():
                new_static['StartPos'][base_dungeons.index(
                    dungeon)][key] = value

    output_static = util.get_master_modpack_dir() / 'aoc' / '0010' / 'Map' / \
        'CDungeon' / 'Static.smubin'
    output_static.parent.mkdir(parents=True, exist_ok=True)
    output_static.write_bytes(
        wszst_yaz0.compress(byml.Writer(new_static, True).get_bytes())
    )
