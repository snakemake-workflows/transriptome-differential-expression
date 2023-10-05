import os
import sys
import pickle as pkl

import matplotlib
matplotlib.use("Agg") # suppress creating of interactive plots
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
import time

from pydeseq2.dds import DeseqDataSet
from pydeseq2.ds import DeseqStats
from pydeseq2.utils import load_example_data

ncpus = snakemake.threads

counts_df = pd.read_csv(f"{snakemake.input.tsv}", sep = '\t', header=0)
# we have a header line containing "Reference" as attribute, hence the following line
# otherwise, we would add an index row, with which we cannot work
counts_df.set_index("Reference", inplace = True)
counts_df = counts_df.T
metadata = pd.read_csv(f"{snakemake.input.coldata}", sep = '\t', header=0, index_col=0)

# filtering low quality samples, first those with NAs
samples_to_keep = ~metadata.condition.isna()
counts_df = counts_df.loc[samples_to_keep]
metadata = metadata.loc[samples_to_keep]

#TODO: make this configurable
# next we filter out counts, with counts lower than 10
genes_to_keep = counts_df.columns[counts_df.sum(axis=0) >= 10]
counts_df = counts_df[genes_to_keep]

dds = DeseqDataSet(
    counts=counts_df,
    metadata=metadata,
    design_factors=["condition"],
    refit_cooks=True,
    n_cpus=ncpus,
)
# fit dispersion(s) and LFCs
dds.deseq2()

# compute normalization factors
dds.fit_size_factors()
# fitting genewise dispersions
dds.fit_genewise_dispersions()

dds.plot_dispersions(save_path=f"{snakemake.output.dispersion_graph}")

# create a clustermap, based on normalized counts
#dds_df = dds.to_df()
#ds_df.to_csv('dds_df.csv')
# getting and applying the scaling factors
sf = dds.obsm["size_factors"]
normalized = counts_df.values.T * sf

# transpose back
normalized = normalized.T

# get indices where the matrix is 0 - may happen
#zero_indices = np.argwhere(normalized == 0)
# TODO: try implementing imputation
# for now, we remove those, which are zeroed
normalized = normalized[~np.all(normalized == 0, axis=1)]

# get column names and row names
column_names = counts_df.columns.values.tolist()
row_names    = counts_df.index.values.tolist()

normalized   = pd.DataFrame(normalized, index = row_names,
                            columns = column_names)
# a_condition:
a_condition = snakemake.config["condition_a_identifier"]
# b_condition
b_condition = snakemake.config["condition_b_identifier"]

# Order columns according to traits - generally column
# order can be arbitrary, but for the headmap, we want. 
a_samples, b_samples = list(), list()
for sample_name in row_names:
    if a_condition in sample_name:
        a_samples.append(sample_name)
    else:
        b_samples.append(sample_name)
assert a_samples, f"list 'a_samples' is empty, '{a_condition}' not unique?"    
assert b_samples, f"list 'b_samples' is empty, '{a_condition}' not unique?"
# total list
samples = a_samples + b_samples

# final orientation and order
normalized = normalized.T[samples]

# get the means of our conditions
a_mean = normalized[a_samples].mean(axis=1)
b_mean = normalized[b_samples].mean(axis=1)

a_over_b = a_mean/b_mean
b_over_a = b_mean/a_mean
# which is bigger?
ratio = list(None for _ in a_over_b)
for index, state in enumerate(a_over_b.ge(b_over_a)):
    if np.isinf(state):
        print("deleting"
              )
        del ratio[index]
        normalized.drop(index, inplace=True)
    if state:
        ratio[index] = a_over_b[index]
    else:
        ratio[index] = b_over_a[index]


normalized["ratio"] = ratio
# now sort according to the ratio
normalized.sort_values("ratio", )
# through away this column
normalized.drop(["ratio"], axis=1, inplace=True)

print(normalized)
#normalized.loc[normalized.index.difference(normalized.dropna(how='all').index)]
#print(normalized)

sns.clustermap(normalized, cmap="mako", linewidths=0)#, xticklables = metadata.index.to_list())#, yticklabels = sta)
plt.savefig(snakemake.output.de_heatmap)
n=snakemake.config["threshold_plot"]
sns.clustermap(normalized.iloc[:n], cmap="mako", linewidths=0)
plt.savefig(snakemake.output.de_top_heatmap)


# compute p-values for our dispersion
stat_res = DeseqStats(dds, n_cpus=ncpus)

# print the summary
stat_res.summary()

#TODO save to file, this is the template code:
#stat_res.results_df.to_csv(os.path.join(OUTPUT_PATH, "results.csv"))

# performing LFC shrinkage

stat_res.lfc_shrink(coeff=f"condition_{b_condition}_vs_{a_condition}")

stat_res.summary()
#TODO: make graph a snakemake target
stat_res.plot_MA(s=20, save_path=f"{snakemake.output.ma_graph}")


#stat_df = stat_res.results_df
# in order produce a heatmap reliably, we need to filter out NAs:
# these CAN happen with p-values for instance. Yet, if the
# p-values is NA, the difference is also minuscule. So, dropping
# is - hopefully always - a non-issue.
#samples_to_keep = ~stat_df.pvalue.isna()
#stat_df = stat_df.loc[samples_to_keep]
#print(stat_df)
#stat_df.to_csv("stat.csv")
##TODO: make parameters configurable
#sns.clustermap(stat_df, cmap="mako") #, xticklables = metadata.index.to_list())#, yticklabels = sta)
#plt.savefig(snakemake.output.de_heatmap)
