#!/usr/bin/env python
# Created: Thu Feb 15 14:22:12 2001
# Last changed: Time-stamp: <01/02/18 11:16:42 thomas>
# Copyright 2000 by Thomas Sicheritz-Ponten.  All rights reserved.
# This code is part of the Biopython distribution and governed by its
# license.  Please see the LICENSE file that should have been included
# as part of this package.
# Authors: Thomas Sicheritz-Ponten and Jan O. Andersson
# thomas@cbs.dtu.dk, http://www.cbs.dtu.dk/thomas
# Jan.O.Andersson@home.se
# flake8: noqa

"""Find next open reading frame in sequence data."""

import re
import sys
import getopt

from Bio import SeqIO
from Bio.Seq import Seq
from Bio.Data import IUPACData, CodonTable


class MissingTable:
    def __init__(self, table):
        self._table = table

    def get(self, codon, stop_symbol):
        try:
            return self._table.get(codon, stop_symbol)
        except CodonTable.TranslationError:
            return "X"


# Make the codon table given an existing table
def makeTableX(table):
    assert table.protein_alphabet == IUPACData.extended_protein_letters
    return CodonTable.CodonTable(
        table.nucleotide_alphabet,
        IUPACData.extended_protein_letters + "X",
        MissingTable(table.forward_table),
        table.back_table,
        table.start_codons,
        table.stop_codons,
    )


class NextOrf:
    def __init__(self, filename, options):
        self.options = options
        self.filename = filename
        self.genetic_code = int(self.options["table"])
        self.table = makeTableX(CodonTable.ambiguous_dna_by_id[self.genetic_code])
        self.counter = 0
        self.ReadFile()

    def ReadFile(self):
        handle = open(self.filename)
        for record in SeqIO.parse(handle, "fasta"):
            self.header = record.id
            direction = self.options["strand"]
            plus = direction in ["both", "plus"]
            minus = direction in ["both", "minus"]
            start, stop = int(self.options["start"]), int(self.options["stop"])
            s = record.seq.upper()
            if stop > 0:
                s = s[start:stop]
            else:
                s = s[start:]
            self.seq = Seq(s)
            self.length = len(self.seq)
            self.rseq = None
            CDS = []
            if plus:
                CDS.extend(self.GetCDS(self.seq))
            if minus:
                self.rseq = self.seq.reverse_complement()
                CDS.extend(self.GetCDS(self.rseq, strand=-1))
            self.Output(CDS)

    def ToFasta(self, header, seq):
        seq = re.sub(
            "(............................................................)",
            "\\1\n",
            seq,
        )
        return f">{header}\n{seq}"

    def Gc(self, seq):
        d = {}
        for nt in "ATGC":
            d[nt] = seq.count(nt)
        gc = d["G"] + d["C"]
        if gc == 0:
            return 0
        return round(gc * 100.0 / (d["A"] + d["T"] + gc), 1)

    def Gc2(self, seq):
        length = len(seq)
        d = {}
        for nt in ["A", "T", "G", "C"]:
            d[nt] = [0, 0, 0]

        for i in range(0, length, 3):
            codon = seq[i : i + 3]
            if len(codon) < 3:
                codon += "  "
            for pos in range(0, 3):
                for nt in ["A", "T", "G", "C"]:
                    if codon[pos] == nt:
                        d[nt][pos] = d[nt][pos] + 1

        gc = {}
        gcall = 0
        nall = 0
        for i in range(0, 3):
            try:
                n = d["G"][i] + d["C"][i] + d["T"][i] + d["A"][i]
                gc[i] = (d["G"][i] + d["C"][i]) * 100.0 / n
            except KeyError:
                gc[i] = 0

            gcall = gcall + d["G"][i] + d["C"][i]
            nall += n

        gcall = 100.0 * gcall / nall
        res = f"{gcall:.1f}%, {gc[0]:.1f}%, {gc[1]:.1f}%, {gc[2]:.1f}%"
        return res

    def GetOrfCoordinates(self, seq):
        n = len(seq)
        start_codons = self.table.start_codons
        stop_codons = self.table.stop_codons
        #        print('Start codons %s' % start_codons)
        #        print('Stop codons %s' % stop_codons)
        frame_coordinates = []
        for frame in range(0, 3):
            coordinates = []
            for i in range(0 + frame, n - n % 3, 3):
                codon = seq[i : i + 3]
                if codon in start_codons:
                    coordinates.append((i + 1, 1, codon))
                elif codon in stop_codons:
                    coordinates.append((i + 1, 0, codon))
            frame_coordinates.append(coordinates)
        return frame_coordinates

    def GetCDS(self, seq, strand=1):
        frame_coordinates = self.GetOrfCoordinates(seq)
        START, STOP = 1, 0
        so = self.options
        nostart = so["nostart"]
        minlength, maxlength = int(so["minlength"]), int(so["maxlength"])
        CDS = []
        f = 0
        for frame in frame_coordinates:
            f += 1
            start_site = 0
            if nostart == "1":
                start_site = 1
            frame.append((self.length, 0, "XXX"))
            for pos, codon_type, codon in frame:
                if codon_type == START:
                    if start_site == 0:
                        start_site = pos
                elif codon_type == STOP:
                    if start_site == 0:
                        continue
                    #                    if codon == 'XXX': print('do something')
                    stop = pos + 2
                    #                    print("stop")
                    length = stop - start_site + 1
                    if length >= minlength and length <= maxlength:
                        if nostart == "1" and start_site == 1:
                            start_site = start_site + f - 1
                        if codon == "XXX":
                            stop = start_site + 3 * (int((stop - 1) - start_site) // 3)
                        s = seq[start_site - 1 : stop]
                        CDS.append((start_site, stop, length, s, strand * f))
                        start_site = 0
                        if nostart == "1":
                            start_site = stop + 1
                    elif length < minlength or length > maxlength:
                        start_site = 0
                        if nostart == "1":
                            start_site = stop + 1
                    del stop
        return CDS

    def Output(self, CDS):
        out = self.options["output"]
        n = len(self.seq)
        for start, stop, length, subs, strand in CDS:
            self.counter += 1
            if strand > 0:
                head = f"orf_{self.counter}:{self.header}:{strand:d}:{start:d}:{stop:d}"
            if strand < 0:
                head = "orf_%s:%s:%d:%d:%d" % (
                    self.counter,
                    self.header,
                    strand,
                    n - stop + 1,
                    n - start + 1,
                )
            if self.options["gc"]:
                head = f"{head}:{self.Gc2(subs)}"

            if out == "aa":
                orf = subs.translate(table=self.genetic_code)
                print(self.ToFasta(head, str(orf)))
            elif out == "nt":
                print(self.ToFasta(head, str(subs)))
            elif out == "pos":
                print(head)


def help():
    global options
    print(f"Usage: {sys.argv[0]} (<options>) <FASTA file>")
    print("")
    print("Options:                                                       default")
    print("--start       Start position in sequence                             0")
    print("--stop        Stop position in sequence            (end of sequence)")
    print("--minlength   Minimum length of orf in bp                          100")
    print("--maxlength   Maximum length of orf in bp, default           100000000")
    print("--strand      Strand to analyse [both, plus, minus]               both")
    print("--frame       Frame to analyse [1 2 3]                             all")
    print("--noframe     Ignore start codons [0 1]                              0")
    print("--output      Output to generate [aa nt pos]                        aa")
    print("--gc          Creates GC statistics of ORF [0 1]                     0")
    print("--table       Genetic code to use (see below)                        1")

    #    for a,b in options.items():
    #        print("\t%s %s" % (a, b)
    #    print("")
    print("\nNCBI's Codon Tables:")
    for key, table in CodonTable.ambiguous_dna_by_id.items():
        print(f"\t{key} {table._codon_table.names[0]}")
    print("\ne.g.")
    print("./nextorf.py --minlength 5 --strand plus --output nt --gc 1 test.fas")
    sys.exit(0)


options = {
    "start": 0,
    "stop": 0,
    "minlength": 100,
    "maxlength": 100000000,
    "strand": "both",
    "output": "aa",
    "frames": [1, 2, 3],
    "gc": 0,
    "nostart": 0,
    "table": 1,
}

if __name__ == "__main__":
    args = sys.argv[1:]
    show_help = len(sys.argv) <= 1

    shorts = "hv"
    longs = [x + "=" for x in options] + ["help"]

    optlist, args = getopt.getopt(args, shorts, longs)
    if show_help:
        help()

    for arg in optlist:
        if arg[0] == "-h" or arg[0] == "--help":
            help()
            sys.exit(0)
        for key in options:
            if arg[1].lower() == "no":
                arg[1] = 0
            elif arg[1].lower() == "yes":
                arg[1] = 1

            if arg[0][2:] == key:
                options[key] = arg[1]

        if arg[0] == "-v":
            print(f"OPTIONS {options}")

    filename = args[0]
    nextorf = NextOrf(filename, options)
