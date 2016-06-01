"""
Some tools for working with chimera sequences generated by SCHEMA.
"""

import pandas as pd
import numpy as np
from sys import exit
import warnings

def contacting_terms (sample_space, contacts):
    """ Lists the possible contacts

    Parameters:
        sample_space (iterable): Each element in sample_space contains the possible
           amino acids at that position
        contacts (iterable): Each element in contacts pairs two positions that
           are considered to be in contact

    Returns:
        contact_terms (list): Each item in the list is a contact in the form
            ((pos1,aa1),(pos2,aa2))
    """
    contact_terms = []
    for contact in contacts:
        first_pos = contact[0]
        second_pos = contact[1]
        first_possibilities = set(sample_space[first_pos])
        second_possibilities = set(sample_space[second_pos])
        for aa1 in first_possibilities:
            for aa2 in second_possibilities:
                contact_terms.append(((first_pos,aa1),(second_pos,aa2)))
    return contact_terms

def make_sequence_terms (sample_space):
    """ List the possible (pos, aa) terms.

    Parameters:
        sample_space (iterable): Each element in sample_space contains the possible
           amino acids at that position

    Returns:
         contact_terms (list): Each item in the list is a contact in the form
            ((pos1,aa1),(pos2,aa2)).
    """
    return [(i,t) for i,sp in enumerate(sample_space) for t in sp]

def X_from_terms(X_terms, all_terms):
    """ Make binary indicator vectors.

    Each row of X is a binary indicator vector indicating whether
    that sequence contains each of the terms of interest. If all_terms
    are single sequence or contact terms, each term should be a tuple.
    Otherwise, if all_terms contains combined terms (as returned by
    make_X), each element in all_terms should be a list of tuples.

    Parameters:
        X_terms (list): list of terms for input sequences.
        all_terms (list): list of all terms being considered.

    Returns:
        X (np.ndarray)
    """
    X = []
    for current_terms in X_terms:
        # determine if all_terms are single terms or collapsed terms
        if isinstance(all_terms[0], tuple):
            inds = [all_terms.index(c) for c in current_terms if c in all_terms]
            X_row = [1 if i in inds else 0 for i in range(len(all_terms))]
        elif isinstance(all_terms[0], list):
            X_row = []
            for terms in all_terms:
                is_in = sum([0 if t in current_terms else 1 for t in terms])
                if is_in > 0:
                    X_row.append(0)
                else:
                    X_row.append(1)
        X.append(X_row)
    return np.array(X)

def make_contact_X (seqs, sample_space, contacts):
    """ Make binary indicator vector for contacts.

    Parameters:
        seqs (list): each sequence should be a string.
        sample_space (iterable): Each element in sample_space contains the possible
           amino acids at that position.
        contacts (iterable): Each element in contacts pairs two positions that
           are considered to be in contact.

    Returns:
        X (np.ndarray)
        contact_terms (list): Each item in the list is a contact in the form
            ((pos1,aa1),(pos2,aa2)).
    """
    contact_X = []
    contact_terms = contacting_terms(sample_space, contacts)
    X_terms = [get_contacts(seq, contacts) for seq in seqs]
    contact_X = X_from_terms(X_terms, contact_terms)
    return contact_X, contact_terms

def make_sequence_X(seqs, sample_space):
    """ Make binary indicator vector for sequence terms.

    Parameters:
        seqs (list): each sequence should be a string.
        sample_space (iterable): ith term should be a tuple listing the
            parental residues at the ith position.

    Returns:
        X (np.ndarray)
        sequence_terms (list): Each item in the list is a term in the form
            (pos,aa).
    """
    sequence_X = []
    sequence_terms = make_sequence_terms(sample_space)
    X_terms = [get_terms(seq) for seq in seqs]
    sequence_X = X_from_terms(X_terms, sequence_terms)
    return sequence_X, sequence_terms

def make_X(seqs, sample_space, contacts, terms=None, collapse=True):
    """ Make combined sequence/structure X.

    If terms are given, the binary indicator vectors indicate whether
    each sequence contains each term. Otherwise, all possible sequence
    and contact terms are computed, and then columns that completely
    covary are combined.

    Parameters:
        seqs (list): each sequence should be a string.
        sample_space (iterable): Each element in sample_space contains
            the possible amino acids at that position.
        contacts (iterable): Each element in contacts pairs two positions
            that are considered to be in contact.
    Optional keyword parameters:
        terms (list):

    Returns:
        X (np.ndarray)
        terms (list): Each item in the list is a list of contact terms,
            sequence terms, or both.
    """
    if terms is not None:
        X_terms = [get_terms(seq) + get_contacts(seq, contacts)
                   for seq in seqs]
        return X_from_terms(X_terms, terms), terms
    seq_X, sequence_terms = make_sequence_X(seqs, sample_space)
    struct_X, contact_terms = make_contact_X(seqs, sample_space, contacts)
    seq_X = seq_X.tolist()
    struct_X = struct_X.tolist()
    X = [seq_X[i] + struct_X[i] for i in range(len(seqs))]
    terms = sequence_terms + contact_terms
    X = np.array(X)
    if not collapse:
        return X, terms
    columns = [i for i in range(len(terms))]
    new_terms = []
    kept_columns = []
    while len(columns) > 0:
        current_col = columns.pop(0)
        kept_columns.append(current_col)
        current = X[:,current_col]
        duplicate_cols = [c for c in columns if
                          np.array_equal(current, X[:,c])]
        new_terms.append([terms[c] for c in [current_col] + duplicate_cols])
        for c in duplicate_cols:
            columns.remove(c)
    X = X[:, kept_columns]
    return X, new_terms

def get_contacts(seq, contacts):
    """ Gets the contacting terms for a sequence.

    Parameters:
        seq (iterable): the sequence
        contacts (iterable): each term should be a tuple listing two
            positions that are in contact with each other.

    Returns:
        contacting_terms (list): each term is of the form
            ((pos1, aa1), (pos2, aa2))
    """
    return [((con[0],seq[con[0]]),(con[1],seq[con[1]]))
              for con in contacts]

def get_terms(seq):
    """ Get the sequence terms.

    Parameters:
        seq (iterable): the sequence

    Returns:
        terms (list): Each item is a (pos,aa) tuple
    """
    return [(i,t) for i,t in enumerate(list(seq))]


def load_assignments (assignments_file):
    """ Convert a SCHEMA assignment file to a dict mapping pos:block.

    Parameters:
        assignments_file (string)

    Returns:
        assignments (dict)
    """
    assignments_line = [l for l in open(assignments_file).read().split('\n')
                        if len(l)>0 and l[0]!='#']
    assignment = [ord(l.split('\t')[2]) - ord('A') for l in assignments_line
                  if l.split('\t')[2] !='-']
    nodes_outputfile = [int(l.split('\t')[1])-1 for l in assignments_line
                        if l.split('\t')[2] !='-'] # -1 because counting 0,1,2...
    return dict(zip(nodes_outputfile, assignment))

def make_sequence (code, assignments_dict, sample_space, default=0):
    ''' Returns the chimera sequence as a list.

    Parameters:
        sequence (iterable): original sequence
        assignments_dict (dict): dict mapping sequence position to block
        sample_space (iterable): ith term should be a tuple listing the
            parental residues at the ith position.
        default (int): Optional keyword paramter. Parent to use for
            positions not assigned to a block.

    Returns:
        seq (list)
    '''
    seq = []
    for pos,aa in enumerate(sample_space):
        # Figure out which parent to use at that position
        if pos in assignments_dict:
            block = assignments_dict[pos] # the assigned block (based on pos)
            # the parent for that block in this particular chimera
            parent = int(code[block])
        else:
            parent = default
            if (np.array(aa) != aa[0]).any():
                warnings.warn('Unassigned block not identical for all parents')
        seq.append (aa[parent])
    return seq

def substitute_blocks(sequence, blocks, assignments_dict, sample_space):
    """ Substitute chimeric blocks into a sequence.

    Parameters:
        sequence (iterable): original sequence
        blocks (iterable): each term in blocks should be tuple (p,b)
            where p is the parent id and b is the block id
        assignments_dict (dict): dict mapping sequence position to block
        sample_space (iterable): ith term should be a tuple listing the
            parental residues at the ith position.

    Returns:
        new_seq (string)
    """
    if len(sequence) != len(sample_space):
        raise ValueError('sequence and sample_space must have the same length')
    new_seq = []
    block_ids = [b for _,b in blocks]
    parent_ids = [p for p,_ in blocks]
    for i,s in enumerate(sequence):
        try:
            current_block = assignments_dict[i]
        except KeyError:
            current_block = -1
        if current_block in block_ids:
            parent = parent_ids[block_ids.index(current_block)]
            new_seq.append(sample_space[i][parent])
        else:
            new_seq.append(s)
    return ''.join(new_seq)

def make_name_dict(dict_file):
    ''' Makes the name dict from a spreadsheet

    The spreadsheet should have a 'name' column and a 'code' column.
    Names will be converted to all-lowercase. Assumes codes are 1-
    indexed and zero-indexes them.

    Parameters:
        dict_file (string): path to Excel file

    Returns:
        res (dict): maps names to chimera codes
    '''
    name_df = pd.read_excel (dict_file)
    name_df['name'] = [s.lower() for s in name_df['name']]
    new_code = [zero_index(c) for c in name_df['code']]
    name_df['code'] = new_code
    name_dict = {a:b for a,b in zip(name_df['name'], new_code)}
    return name_dict

def zero_index (code):
    '''
    Takes a 1-indexed chimera code and zero-indexes it
    '''
    return ''.join([str(int(x)-1) for x in str(code)])

def translate(na_sequence):
    """ Translates a nucleic acid string."""
    codon_dict = {'ATT':'I', 'ATC': 'I', 'ATA': 'I', 'CTG': 'L',
                  'CTC': 'L', 'CTA': 'L', 'CTT': 'L', 'TTA': 'L', 'TTG': 'L',
                  'GTG':'V', 'GTC':'V', 'GTA':'V', 'GTT':'V',
                  'TTT':'F','TTC':'F',
                  'ATG':'M',
                  'TGC':'C','TGT':'C',
                  'GCG':'A','GCT':'A', 'GCC':'A', 'GCA':'A',
                  'GGC':'G', 'GGT':'G', 'GGA':'G', 'GGG':'G',
                  'CCG':'P','CCT':'P', 'CCC':'P', 'CCA':'P',
                  'ACC':'T', 'ACT':'T', 'ACA':'T', 'ACG':'T',
                  'AGC':'S','TCT':'S', 'TCC':'S', 'TCA':'S', 'TCG':'S', 'AGT':'S',
                  'TAT':'Y','TAC':'Y',
                  'TGG':'W',
                  'CAG':'Q','CAA':'Q',
                  'AAC':'N','AAT':'N',
                  'CAC':'H','CAT':'H',
                  'GAA':'E','GAG':'E',
                  'GAT':'D','GAC':'D',
                  'AAA':'K','AAG':'K',
                  'CGT':'R', 'CGC':'R', 'CGA':'R', 'CGG':'R', 'AGA':'R', 'AGG':'R',
                  'TAA':'.', 'TAG':'.', 'TGA':'.'}
    if len(na_sequence) % 3 != 0:
        raise ValueError('na_sequence must have length divisible by 3.')
    translated = ''
    for i in range(len(na_sequence)/3):
        codon = na_sequence[3*i:3*i+3].upper()
        try:
            translated += codon_dict[codon]
        except KeyError:
            translated += '-'
    return translated
