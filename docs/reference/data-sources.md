# Data sources

## Dataset and attribution

Cecropis reads **MaleCNS v1.0, minconf=0.5** directed connectivity and matching annotations. Obtain them from the [official download page](https://male-cns.janelia.org/download/). Source distributions do not bundle or rehost the large datasets. The official data license is [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

The source is the MaleCNS project and its collaborators: HHMI Janelia FlyEM, University of Cambridge Department of Zoology, MRC Laboratory of Molecular Biology and Google Research. Retain the official source, version, license link and accompanying provenance. When sharing extracted or transformed data, describe the processing and do not imply endorsement of your results.

The data license is separate from Cecropis's original code and documentation, licensed under [Apache-2.0](../../LICENSE), Copyright 2026 Ziyu Huang. Fonts retain their own licenses; see [NOTICE](../../NOTICE).

## Required files

The required inputs are the connectivity and annotation Feather files listed in [Downloads](../guides/downloads.md). Obtain both from the same dataset version. Connectivity provides directed connection counts; annotations provide names, types, status and available locations.

Body IDs identify source objects and remain unchanged in Cecropis. Default neuron queries use `Traced` records; other statuses and unannotated endpoints remain distinct. An object without a neuronal annotation is not automatically classified as a neuron.

## Optional morphology

The spatial view can also use real skeletons from the same dataset. Cecropis uses unmirrored EM coordinates; do not mix them with mirrored or template-transformed files. See [Geometry](../guides/geometry.md) for preparation and units.

Skeleton branches describe neuron shape; inter-neuron connections come from the connectivity table. Activity colors and response curves show calculated model responses.

## README screenshots

The screenshots in `docs/images/` were captured in Cecropis using MaleCNS v1.0 data from the collaborators credited above, under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). The spatial view simplifies skeleton branches for the global overview; the group view aggregates directed connection counts for selected neurons by type. Response curves and activity colors are calculated by Cecropis's propagation model. Node IDs and annotations retain their source meanings.

Cecropis's Apache-2.0 license covers its original interface and documentation. The MaleCNS data shown in the screenshots retains its own attribution and license; include this source information when reusing the images.
