#!/usr/bin/env python
# -*- coding: utf-8  -*-
import sys
import ast 
import warnings
import pathlib

import click

import numpy as np

from . import _dedup, _fileio, _pairsam_format, _headerops, cli, common_io_options
from .pairsam_markasdup import mark_split_pair_as_dup


UTIL_NAME = 'pairsam_dedup'

# you don't need to load more than 10k lines at a time b/c you get out of the 
# CPU cache, so this parameter is not adjustable
MAX_LEN = 10000

@cli.command()
@click.argument(
    'pairsam_path', 
    type=str,
    required=False)
@click.option(
    "-o", "--output", 
    type=str, 
    default="", 
    help='output file for pairs after duplicate removal.'
        ' If the path ends with .gz or .lz4, the output is pbgzip-/lz4c-compressed.'
        ' By default, the output is printed into stdout.')
@click.option(
    "--output-dups",
    type=str, 
    default="", 
    help='output file for duplicated pairs. '
        ' If the path ends with .gz or .lz4, the output is pbgzip-/lz4c-compressed.'
        ' If the path is the same as in --output or -, output duplicates together '
        ' with deduped pairs. By default, duplicates are dropped.')
@click.option(
    "--output-unmapped",
    type=str, 
    default="", 
    help='output file for unmapped pairs. '
        'If the path ends with .gz or .lz4, the output is pbgzip-/lz4c-compressed. '
        'If the path is the same as in --output or -, output unmapped pairs together '
        'with deduped pairs. If the path is the same as --output-dups, output '
        'unmapped reads together with dups. By default, unmapped pairs are dropped.')
@click.option(
    "--output-stats", 
    type=str, 
    default="", 
    help='output file for duplicate statistics. '
        ' If file exists, it will be open in the append mode.'
        ' If the path ends with .gz or .lz4, the output is pbgzip-/lz4c-compressed.'
        ' By default, statistics are not printed.')
@click.option(
    "--max-mismatch",
    type=int, 
    default=3,
    help='Pairs with both sides mapped within this distance (bp) from each '
         'other are considered duplicates.')
@click.option(
    '--method',
    type=click.Choice(['max', 'sum']),
    default="max",  
    help='define the mismatch as either the max or the sum of the mismatches of'
        'the genomic locations of the both sides of the two compared molecules',
    show_default=True,)
@click.option(
    "--sep",
    type=str, 
    default=_pairsam_format.PAIRSAM_SEP_ESCAPE, 
    help=r"Separator (\t, \v, etc. characters are "
          "supported, pass them in quotes) ")
@click.option(
    "--comment-char", 
    type=str, 
    default="#", 
    help="The first character of comment lines")
@click.option(
    "--send-header-to", 
    type=click.Choice(['dups', 'dedup', 'both', 'none']),
    default="both", 
    help="Which of the outputs should receive header and comment lines")
@click.option(
    "--c1", 
    type=int, 
    default=_pairsam_format.COL_C1,  
    help='Chrom 1 column; default {}'.format(_pairsam_format.COL_C1))
@click.option(
    "--c2", 
    type=int, 
    default=_pairsam_format.COL_C2,  
    help='Chrom 2 column; default {}'.format(_pairsam_format.COL_C2))
@click.option(
    "--p1", 
    type=int, 
    default=_pairsam_format.COL_P1,  
    help='Position 1 column; default {}'.format(_pairsam_format.COL_P1))
@click.option(
    "--p2", 
    type=int, 
    default=_pairsam_format.COL_P2,  
    help='Position 2 column; default {}'.format(_pairsam_format.COL_P2))
@click.option(
    "--s1", 
    type=int, 
    default=_pairsam_format.COL_S1,  
    help='Strand 1 column; default {}'.format(_pairsam_format.COL_S1))
@click.option(
    "--s2", 
    type=int, 
    default=_pairsam_format.COL_S2,  
    help='Strand 2 column; default {}'.format(_pairsam_format.COL_S2))
@click.option(
    "--unmapped-chrom", 
    type=str, 
    default=_pairsam_format.UNMAPPED_CHROM,  
    help='Placeholder for a chromosome on an unmapped side; default {}'.format(_pairsam_format.UNMAPPED_CHROM))
@click.option(
    "--mark-dups", 
    is_flag=True,
    help='If specified, duplicate pairs are marked as DD in "pair_type" and '
         'as a duplicate in the sam entries.')

@common_io_options

def dedup(pairsam_path, output, output_dups, output_unmapped,
    output_stats,
    max_mismatch, method, 
    sep, comment_char, send_header_to,
    c1, c2, p1, p2, s1, s2, unmapped_chrom, mark_dups, **kwargs
    ):
    '''find and remove PCR duplicates.

    Find PCR duplicates in an upper-triangular flipped sorted pairs/pairsam 
    file. Allow for a +/-N bp mismatch at each side of duplicated molecules.

    PAIRSAM_PATH : input triu-flipped sorted .pairs or .pairsam file.  If the
    path ends with .gz/.lz4, the input is decompressed by pbgzip/lz4c. 
    By default, the input is read from stdin.
    '''
    dedup_py(pairsam_path, output, output_dups, output_unmapped,
        output_stats,
        max_mismatch, method, 
        sep, comment_char, send_header_to,
        c1, c2, p1, p2, s1, s2, unmapped_chrom, mark_dups,
        **kwargs
        )


def dedup_py(
    pairsam_path, output, output_dups, output_unmapped,
    output_stats,
    max_mismatch, method, 
    sep, comment_char, send_header_to,
    c1, c2, p1, p2, s1, s2, unmapped_chrom, mark_dups,
    **kwargs
    ):
    sep = ast.literal_eval('"""' + sep + '"""')
    send_header_to_dedup = send_header_to in ['both', 'dedup']
    send_header_to_dup = send_header_to in ['both', 'dups']

    instream = (_fileio.auto_open(pairsam_path, mode='r', 
                                  nproc=kwargs.get('nproc_in'),
                                  command=kwargs.get('cmd_in', None)) 
                if pairsam_path else sys.stdin)
    outstream = (_fileio.auto_open(output, mode='w', 
                                   nproc=kwargs.get('nproc_out'),
                                   command=kwargs.get('cmd_out', None)) 
                 if output else sys.stdout)

    if not output_dups:
        outstream_dups = None
    elif (output_dups == '-' or 
          (pathlib.Path(output_dups).absolute() == pathlib.Path(output).absolute())):
        outstream_dups = outstream
    else:
        outstream_dups = _fileio.auto_open(output_dups, mode='w', 
                                            nproc=kwargs.get('nproc_out'),
                                            command=kwargs.get('cmd_out', None)) 
        
    if not output_unmapped:
        outstream_unmapped = None
    elif (output_unmapped == '-' or 
        (pathlib.Path(output_unmapped).absolute() == pathlib.Path(output).absolute())):
        outstream_unmapped = outstream
    elif (pathlib.Path(output_unmapped).absolute() == pathlib.Path(output_dups).absolute()):
        outstream_unmapped = outstream_dups
    else:
        outstream_unmapped = _fileio.auto_open(output_unmapped, mode='w', 
                                            nproc=kwargs.get('nproc_out'),
                                            command=kwargs.get('cmd_out', None))
                             

    header, body_stream = _headerops.get_header(instream)
    header = _headerops.append_new_pg(header, ID=UTIL_NAME, PN=UTIL_NAME)

    if send_header_to_dedup:
        outstream.writelines((l+'\n' for l in header))
    if send_header_to_dup and outstream_dups and (outstream_dups != outstream):
        outstream_dups.writelines((l+'\n' for l in header))
    if (outstream_unmapped and (outstream_unmapped != outstream) 
            and (outstream_unmapped != outstream_dups)):
        outstream_unmapped.writelines((l+'\n' for l in header))

    n_unmapped, n_dups, n_nodups = streaming_dedup(
        method, max_mismatch, sep, 
        c1, c2, p1, p2, s1, s2, unmapped_chrom,
        body_stream, outstream, outstream_dups, outstream_unmapped, mark_dups)

    if output_stats:
        stat_f = _fileio.auto_open(output_stats, mode='a',
                                   nproc=kwargs.get('nproc_out'),
                                   command=kwargs.get('cmd_out', None))
        stat_f.write('{}\t{}\n'.format('n_unmapped', n_unmapped))
        stat_f.write('{}\t{}\n'.format('n_dups', n_dups))
        stat_f.write('{}\t{}\n'.format('n_nodups', n_nodups))
        stat_f.close()

    if instream != sys.stdin:
        instream.close()

    if outstream != sys.stdout:
        outstream.close()

    if outstream_dups and (outstream_dups != outstream):
        outstream_dups.close()

    if (outstream_unmapped and (outstream_unmapped != outstream) 
            and (outstream_unmapped != outstream_dups)):
        outstream_unmapped.close()

def fetchadd(key, mydict):
    key = key.strip()
    if key not in mydict:
        mydict[key] = len(mydict)
    return mydict[key]


def ar(mylist, val):
    return np.array(mylist, dtype={8: np.int8, 16: np.int16, 32: np.int32}[val])
    

def streaming_dedup(
        method, max_mismatch, sep,
        c1ind, c2ind, p1ind, p2ind, s1ind, s2ind,
        unmapped_chrom,
        instream, outstream, outstream_dups, outstream_unmapped,
        mark_dups):
    maxind = max(c1ind, c2ind, p1ind, p2ind, s1ind, s2ind)

    dd = _dedup.OnlineDuplicateDetector(method, max_mismatch, returnData=False)

    c1 = []; c2 = []; p1 = []; p2 = []; s1 = []; s2 = []
    line_buffer = []
    cols_buffer = []
    chromDict = {}
    strandDict = {}
    n_unmapped = 0
    n_dups = 0
    n_nodups = 0
    curMaxLen = max(MAX_LEN, dd.getLen())

    while True: 
        line = next(instream, None)
        stripline = line.strip() if line else None

        if line:
            if not stripline: 
                warnings.warn("Empty line detected not at the end of the file")
                continue    

            cols = line.split(sep)
            if len(cols) <= maxind:
                raise ValueError(
                    "Error parsing line {}: ".format(line)
                    + " expected {} columns, got {}".format(maxind, len(cols)))
                
            if ((cols[c1ind] == unmapped_chrom)
                or (cols[c2ind] == unmapped_chrom)):

                if outstream_unmapped:
                    outstream_unmapped.write(line)  
                n_unmapped += 1
                    
            else:
                line_buffer.append(line)
                if mark_dups:
                    cols_buffer.append(cols)

                c1.append(fetchadd(cols[c1ind], chromDict))
                c2.append(fetchadd(cols[c2ind], chromDict))
                p1.append(int(cols[p1ind]))
                p2.append(int(cols[p2ind]))
                s1.append(fetchadd(cols[s1ind], strandDict))
                s2.append(fetchadd(cols[s2ind], strandDict))
                
        if (not line) or (len(c1) == curMaxLen):
            res = dd.push(ar(c1, 8), 
                          ar(c2, 8), 
                          ar(p1, 32), 
                          ar(p2, 32), 
                          ar(s1, 8), 
                          ar(s2, 8))
            if not line:
                res = np.concatenate([res, dd.finish()])

            for i in range(len(res)): 
                if not res[i]:
                    outstream.write(line_buffer[i])  
                    n_nodups += 1
                else:
                    n_dups += 1
                    if outstream_dups:
                        if mark_dups:
                            outstream_dups.write(sep.join(
                                mark_split_pair_as_dup(cols_buffer[i])))
                        else:
                            outstream_dups.write(line_buffer[i])
                    
            c1 = []; c2 = []; p1 = []; p2 = []; s1 = []; s2 = []
            line_buffer = line_buffer[len(res):]
            if mark_dups:
                cols_buffer = cols_buffer[len(res):]
            if not line:
                if(len(line_buffer) != 0):                
                    raise ValueError(
                        "{} lines left in the buffer, ".format(len(line_buffer))
                        + "should be none;"
                        + "something went terribly wrong")
                break

    return n_unmapped, n_dups, n_nodups


if __name__ == '__main__':
    dedup()
