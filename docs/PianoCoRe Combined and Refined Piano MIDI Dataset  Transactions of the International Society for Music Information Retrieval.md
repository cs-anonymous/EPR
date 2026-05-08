---
title: "PianoCoRe: Combined and Refined Piano MIDI Dataset | Transactions of the International Society for Music Information Retrieval"
source: "https://transactions.ismir.net/articles/10.5334/tismir.333"
author:
  - "[[Ilya Borovik]]"
published:
created: 2026-05-07
description:
tags:
  - "clippings"
---
## PianoCoRe: Combined and Refined Piano MIDI Dataset

## DATASET ARTICLE

- Ilya Borovik

## Abstract

具有匹配乐谱和演奏的符号音乐数据集对于许多音乐信息检索（MIR）任务是必不可少的。然而，现有的资源通常只覆盖了一小部分作曲家，缺乏演奏的多样性，忽略了音符级别的对齐，或者使用不一致的命名格式。这项工作提出了一个大型钢琴MIDI数据集，它统一并提炼了主要的开源钢琴语料库。该数据集包含483位作曲家的5625首作品的250,046场演出，总计21,763小时。PianoCoRe以分层子集发布，以支持不同的应用程序：从大规模分析和预训练（**PianoCoRe- c 和重复数据删除PianoCoRe- b**）到具有音符级分数对齐的表达性能建模（**PianoCoRe-A/A\***）。音符对齐子集，**PianoCoRe-A**，提供了迄今为止最大的157,207个与1,591个分数对齐的表演的开源集合。除了数据集之外，贡献还包括：(1)用于检测损坏和类似分数的转录的MIDI质量分类器，以及(2)RAScoP，一种清理时间对齐错误并插入缺失音符的对齐优化管道。分析表明，该改进降低了时间噪声，消除了速度异常值。此外，与在原始数据集或较小数据集上训练的模型相比，在PianoCoRe上训练的具有表现力的性能渲染模型对未见片段的鲁棒性有所提高。PianoCoRe为下一代富有表现力的钢琴演奏研究提供了一个现成的基础。

Year: 2026

[Volume: 9 Issue: 1](https://transactions.ismir.net/en/11/volume/9/issue/1)

Page/Article: 144–163

[DOI: 10.5334/tismir.333](https://doi.org/10.5334/tismir.333)

Submitted on Aug 17, 2025

Accepted on Mar 16, 2026

Published on Apr 27, 2026

Peer Reviewed

[CC Attribution 4.0](https://creativecommons.org/licenses/by/4.0)

## 1 Introduction

乐谱和现场表演是广泛的音乐信息检索（MIR）任务的基本数据源。乐谱提供了书面作品的象征性表现，而表演则通过时间、动态和发音的变化捕捉了音乐家的独特诠释。建模这两个领域之间的关系对于分析表演者为向观众传达音乐结构和情感而做出的决定至关重要。此外，配对得分-表现数据支持计算表达性能呈现，其中训练模型模拟人类解释。对于所有这些任务，可用数据集的规模、质量和结构是必不可少的。

对于钢琴音乐，已经开发了许多符号语料库来支持计算性能分析和建模(**[Cancino‑Chacón et al., 2018](#r6)**；**[爱默生和哈里森，2025](#r11)**；**[Lerch et al., 2020](#r30)**)。这些资源分为两类。第一种包括从计算机监控的声学钢琴（例如，Yamaha Disklavier）捕获的高保真录音(**[Foscarin等人，2020](#r12)**；**(Goebl 1999) (# r13) ** ;**[Hashida等，2018](#r16)**；**[Hawthorne et al., 2019](#r17)**；**[Hu and Widmer, 2023](#r20)**)。第二类依赖于自动音乐转录（AMT） （**[Benetos等人，2018](#r1)**）从录音中生成大规模数据集(**[Bradshaw和Colton， 2025](#r4)**；**[Edwards et al., 2009](#r9)**；**[Kong et ., 2022](#r25)**；**[Lee et al., 2025](#r29)**；**[张等，2022](#r52)**)。虽然记录的数据集提供了无与伦比的表达细节，但它们通常在规模和风格多样性方面受到限制。相反，基于AMT的数据集提供多样性，但往往包含转录错误，缺乏精确的笔记级比对。此外，不兼容的命名方案和元数据标准使得很难在不冒信息泄漏风险的情况下组合数据集。总之，这些挑战突出了一个严重的差距：缺乏统一的资源，将转录数据的规模与记录表现的准确性结合起来，所有这些都与分数保持一致。

这一差距由**PianoCoRe**解决，[^2]是一个综合数据集，结合并改进了最大的开源钢琴乐谱和表演语料库。piano coore收录了483位作曲家的5625件作品的250,046场演出的21,763小时的钢琴音乐，其中75.3%的演出都有乐谱。为了使这些数据在不同的应用程序中可用，它以分层子集发布：

- **PianoCoRe - C:** 一个完整的混合源钢琴演奏集合；
- **PianoCoRe - B:** 用于大规模预训练的重复数据删除和质量评估子集；
- **PianoCoRe - A:** 一个包含与分数对齐的表演的子集；和
- **PianoCoRe - A\*:** 一个高质量的子集，最好的质量性能和音符级对齐。

与之前的努力不同，PianoCoRe通过将内容限制在欧盟公共领域的作品，专注于法律上的可持续性，确保其仍然是学术界的稳定和健全的资源。为了支持不同的用例，数据集被归档在Zenodo上[^3]，镜像在hug Face上[^4]。

通过提供一个比以前的资源更大、更清晰的注释数据集，这项工作为开发更智能的计算钢琴演奏模型奠定了基础。

工作的主要贡献有：

这项工作的其余部分结构如下：[第2节]（#s2）回顾了相关的钢琴数据集。[第3节]（#s3）详细介绍了PianoCoRe的策展过程。[第4节]（#s4）介绍了MIDI质量分类器和重复数据删除子集。[第5节]（#s5）介绍了RAScoP和注释对齐子集。[第6节]（#s6）评估PianoCoRe的表现力表现。最后，[第7节]（#s7）和[^1]讨论了局限性并对工作进行了总结。

## 2 Related Work

本节提供了最突出的钢琴乐谱和性能数据集的概述，按主要数据源和预期应用进行分类。[表1]（#T1）提供了与PianoCoRe相关的数据集和PianoCoRe本身的统计数据的摘要。

表1

主要符号钢琴演奏数据集和**PianoCoRe**数据集及其层的比较。来源：R-recorded (Disklavier/Hardware), T - transcript (Audio - to - MIDI)， T -红旗转录标记为高质量。元数据：p -表演者，s -钢琴独奏概率，d -重复数据删除标志，q -质量标签。<sup>†</sup>注释不是对所有性能都可用。<sup>‡</sup>从原始元数据计算的唯一作曲家名称的数量，而不是手动验证。

| Dataset | Composers | Pieces | Performances | Hours | Sources | Scores | Alignments | Metadata |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| MAESTRO | 43 | – | 1,276 | 199 | R | no | no | P |
| (n)ASAP | 16 | 222 | 1,067 | 92 | R | 100% | beat/note | P |
| GiantMIDI | 2,786 | 10,855 | 10,855 | 1,237 | T | no | no | S |
| ATEPP | 25 | 1,596 | 11,742 | 1,009 | T | 43.6% | no | P, Q <sup>†</sup> |
| Aria‑MIDI | 19,021 <sup>‡</sup> | – | 1,186,253 | 100,629 | T | no | no | S, P <sup>†</sup> |
| PERiScoPe | 82 | 2,738 | 46,473 | 3,784 | R, T | 81.9% | note | P <sup>†</sup> |
| **PianoCoRe‑C** | **483** | **5,625** | **250,046** | **21,763** | **R, T** | **75.3%** | **no** | **P** <sup>†</sup> |
| **PianoCoRe‑B** | **478** | **5,591** | **214,092** | **18,757** | **R, T** | **75.0%** | **no** | **P** <sup>†</sup>**, D, Q** |
| **PianoCoRe‑A** | **151** | **1,591** | **157,207** | **12,509** | **R, T** | **100%** | **note** | **P** <sup>†</sup>**, D, Q** |
| **PianoCoRe‑A\*** | **137** | **1,517** | **130,275** | **10,330** | **R, T‑HQ** | **100%** | **note** | **P** <sup>†</sup>**, D, Q** |

### 2.1 Recorded MIDI performance datasets

一类数据集由直接从计算机监控钢琴（例如，雅马哈Disklavier）上的人类表演中捕获的MIDI文件组成。这些表演在象征层面上提供了表达细节的最高保真度。

**MAESTRO**数据集（**[Hawthorne等人，2019](#r17)**）是该类别中最具影响力的数据集，其中包含来自国际钢琴比赛的200多小时的精湛演奏。高质量，时间对齐的音频- midi对使其成为转录基准的标准。然而，按照现代深度学习的标准，它的规模和多样性并不大。

ASAP数据集（**[Foscarin et al., 2020](#r12)**）通过添加乐谱和节拍注释来扩展MAESTRO。该数据集包含来自MAESTRO的1,067次演出中的近92小时，按节拍级别排列到222个独特的分数。它的扩展，**(n)ASAP** (**[Peter et al., 2023](#r38)**)，增加了音符级对齐，使其成为最大的开源记录MIDI数据集，具有分数到性能的音符对齐。

几个较小的策划数据集为专门的分析任务提供了特殊的细节。**Batik - plays - Mozart**语料库（**[Hu和Widmer， 2023](#r20)**）在莫扎特奏鸣曲的专业MIDI演奏和专家注释的乐谱之间提供音符对音符的对齐。**维也纳4x22钢琴语料库** (**[Goebl, 1999](#r13)**)收录了22位钢琴家演奏的四首古典音乐选段。**SMD** (**[m<s:1> ller et al., 2011](#r35)**)为11位作曲家的50部作品的50场演出提供完美同步的音频和MIDI。**MazurkaBL** （**[Kosta等人，2018](#r27)**）为肖邦玛祖卡的2000个录音提供了与乐谱一致的节拍、响度和表达标记。**CrestMusePEDB** (**[Hashida et al., 2018](#r16)**)包含12位钢琴家的35首古典作品的411次音符对齐表演。而无价的详细研究，这些数据集的狭窄范围限制了他们的效用训练通用性能模型。

### 2.2 Large‑scale transcribed MIDI datasets

为了避免收集配备传感器的钢琴上记录的MIDI数据的耗时过程，研究人员越来越多地使用AMT （**[Benetos et al., 2018](#r1)**）从公开可用的音频中生成大型数据集。

**GiantMIDI - Piano** (**[Kong et al., 2022](#r25)**)是早期的大型钢琴转录工作（**[Kong et al., 2021](#r26)**），在10,855个曲目中提供1,237小时的古典钢琴MIDI。音频来自从YouTube下载的IMSLP曲目的表演，涵盖了广泛的音乐时期的作品。然而，GiantMIDI‑Piano不提供任何乐谱，并且元数据包含重复和不一致（参见[Section 3.3.3](#s3_3_3)）。

**ATEPP**数据集（**[Zhang et al., 2022](#r52)**）捕获了著名钢琴家的11,674场演出，总计超过1,007小时的转录音乐。大约有一半的演出是没有任何音阶对齐的配对乐谱。ATEPP为某些性能提供了质量标签（“高质量”，“低质量”，“损坏”）。然而，正如[第4.2节]（#s4_2）所分析的那样，存在未标记的损坏转录。

**咏叹调- MIDI** (**[Bradshaw and Colton, 2025](#r4)**)极大地扩展了数据规模维度，提供超过100,629小时的转录钢琴音乐。数据被抓取，分类为钢琴独奏，并使用大型语言模型引导的管道进行注释。Aria - MIDI的大小使其对自我监督学习很有价值。然而，该数据集缺乏符号乐谱和音乐作品的完整注释。

其他值得注意的工作包括**SUPRA**数据集（**[Shi等人，2019](#r40)**），该数据集数字化了478架钢琴滚动演奏的52小时档案。在钢琴爵士乐领域，**PiJAMA**数据集（**[Edwards等人，2023](#r9)**）提供了120名钢琴家2,777场演出的223小时高质量转录。

### 2.3 Mixed‑source piano datasets

尽管上述数据集很有价值，但它们是独立存在的，每个数据集都有不同的结构和元数据约定。直接混合它们进行钢琴演奏建模会带来训练和测试分割之间信息泄露的风险。

**GigaMIDI** （**[Lee等人，2025](#r29)**）包含超过140万个MIDI文件，来自不同的单乐器和多乐器来源，包括ASAP， ATEPP, GiantMIDI - Piano, Vienna 422， SMD和蜡染演奏-莫扎特。一个有价值的贡献是用于对非表达性MIDI数据进行分类的启发式集合。然而，在GigaMIDI中，非标准化的片段标题使基于片段的分组和数据比较变得复杂。

**PERiScoPe**数据集（**[Borovik等人，2025](#r2)**）代表了弥合记录和基于转录的MIDI数据集之间差距的努力。它包含超过35,000个音符对齐的分数-性能对，匹配和组合(n)ASAP和ATEPP与2158小时的网络收集的音频转录到MIDI。

所描述的单源和多源数据集面临着**PianoCoRe**旨在解决的几个限制。首先，集合通常缺乏标准化的、易于导航的目录结构和经过验证的元数据，这使得它们难以组合和扩展。其次，数据集可能会由于包含现代版权作品而带来法律风险。最后，MIDI转录可能会被复制、损坏或转录乐谱音频，而这些音频无法为性能分析和建模提供信息。

## 3 PianoCoRe Dataset

本节详细介绍了**PianoCoRe**的构造。它提出了一种处理乐谱的方法；匹配工作跨不同的数据集；预处理源文件，以解决不一致；并将它们整合成一个统一的、可导航的集合。最后的数据集在本节的末尾。

### 3.1 Notation and definitions

The core entities and relations used throughout the manuscript and in the data collection and processing pipelines are as follows:

- **Note,** $n$ **:** a MIDI note described by its pitch $p$, onset $o$, duration $d$, and velocity $v$: $n = \left(\right. p , o , d , v \left.\right)$. Notes are indexed $i \in \left\{\right. 1 , \ldots , N \left.\right\}$ after sorting MIDI by onset, pitch, and duration;
- **Musical score,** $y$ **:** a sequence of $N_{s}$ score MIDI notes $\left(\right. y_{1} , \ldots , y_{N_{s}} \left.\right)$;
- **Performance,** $x$ **:** a sequence of $N_{p}$ performance MIDI notes $\left(\right. x_{1} , \ldots , x_{N_{p}} \left.\right)$; and
- **Alignment,** $A$ **:** a sequence of score and performance notes pairs $\left\{\right. \left(\right. y_{i} , x_{j} \left.\right) : y_{i} \in y \cup \left\{\right. \emptyset \left.\right\} , x_{j} \in x \cup \left\{\right. \emptyset \left.\right\} \left.\right\}$, where $a_{i j} = \left(\right. y_{i} , \emptyset \left.\right)$ indicates a missing performed note and $a_{i j} = \left(\right. \emptyset , x_{i} \left.\right)$ – an inserted performance note. The number of matched notes (pairs with $y_{i} \neq \emptyset \land x_{i} \neq \emptyset$) is denoted as $N_{m}$.

The following four primary ratios are used to evaluate the relationship between a score and a performance:

- **Note Ratio,** $R_{n}$ **:** a ratio of the number of notes between performance and score sequences:  
	(1) $R_{n} = \frac{N_{p}}{N_{s}}$  
	Given the same musical content, note ratio identifies structural discrepancies, such as omitted repeats ($R_{n} \ll 1$) or transcription noise ($R_{n} \gg 1$);
- **Alignment Recall,** $R_{a}$ **:** a proportion of score notes matched to the performance:  
	(2) $R_{a} = \frac{N_{m}}{N_{s}} \leq 1$  
	Recall represents the ‘completeness’ of the performance relative to the score;
- **Alignment Precision,** $P_{a}$ **:** a proportion of performed notes matched to the score:  
	(3) $P_{a} = \frac{N_{m}}{N_{p}} \leq 1$  
	High precision indicates a clean performance with few noisy notes or insertions;
- **Adjusted Alignment Ratio,** $R_{a}^{′}$ **:** a relaxed quality metric that takes the highest of Recall (when $N_{p} \geq N_{s}$) and Precision ($N_{p} < N_{s}$):  
	(4) $R_{a}^{′} = \frac{N_{m}}{min \left(\right. N_{s} , N_{p} \left.\right)} = max \left(\right. P_{a} , R_{a} \left.\right) \leq 1$  
	It ensures that a performance is not penalized for missing notes (e.g., skipped repeats) as long as the played notes match the score, and is not penalized for extra notes (e.g., transcription noise) as long as all score notes are present.

Furthermore, the two common types of symbolic errors handled during preprocessing are:

- **Duplicate Notes:** two or more notes having the exact same pitch, onset time, and duration and
- **Overlapping Notes:** a condition where a note $n_{i}$ of pitch $p$ starts while a previous note $n_{i - 1}$ of the same pitch is still active ($o_{i} < o_{i - 1} + d_{i - 1}$).

### 3.2 Data‑matching methodology

乐谱和表演音乐数据集的基本部分是乐谱和表演的正确匹配。一种方法是使用组合实体解析(**[Kong et al., 2022](#r25)**；**[Zhang et al., 2022](#r52)**)，比较得分和性能文件的标题和可用元数据。但是，如果文件被错误标记或具有唯一的命名格式，则音乐内容可能无法反映标题。

MIDI - to - MIDI匹配用于组合数据集。这使得人们可以直接比较乐谱和表演中的音符。它还允许将表演与仅以MIDI格式提供并且没有MusicXML （**[Good, 2001](#r14)**）对应的乐谱相匹配。最后，它允许在没有分数可用的情况下将性能与其他性能进行匹配，以获得更多标记数据。

#### 3.2.1 Score processing

在匹配之前，使用partitura库（**[Cancino‑Chacón et al., 2022](#r7)**）将MusicXML文件转换为MIDI格式，并进行以下改进：

- **动态和节奏：** <sound>标签和动态属性的音符被处理嵌入动态和节奏的性能方向标记直接到音符速度和节奏变化的分数MIDI文件。
- **装饰物：**颤音和装饰物是基于MusicXML中可用的不可见音符展开的（<cue/>或print - object=“no”）。基础可见装饰音符被移除，以避免重叠音符事件。
- **Grace Notes:** acciaccatura和apapogiatura音符根据定义进行扩展。即兴音符在拍子前以32音的顺序出现。附音偷走了主音的音长。
**重复：**对于重复的分数，创建两个版本：一个*最大*版本，所有重复都展开，一个*最小*版本，每个重复只播放一次（后缀\_mini在文件名中）。

这些变化确保公平考虑的分数结构和性能特定元素在MIDI分数文件。为了简化创建的数据集的管理，没有考虑分数中可能重复结构的全部集合。

#### 3.2.2 Candidate pair selection

为了避免对所有文件进行暴力比较，执行一个过滤步骤来识别较小的候选对集。如果符合以下标准，则得分与表演相匹配：

**作曲家：**作曲家的名字，从文件路径或元数据标签中提取，匹配；
- **音符计数：**音符比率$R_{n}$落在接近长度的合理范围内：$0.75 \leq R_{n} \leq 1.33$；和
- **关键词：**如果可用，目录编号和标题内的关键/规模信息匹配。

这种预滤波可以有效地应用计算密集型、基于对齐的验证。

#### 3.2.3 Note alignment and verification

For the final step, note‑level alignments for candidate pairs were computed using the DualDTWNoteMatcher from Parangonar (**[Peter, 2023](#r37)**). The underlying dynamic time warping (DTW) implementation was optimized using Numba's just‑in‑time (JIT) compilation (**[Lam et al., 2015](#r28)**). The optimized version works, on average, 12 times faster on the ASAP dataset. This optimization was essential for performing millions of pairwise alignments within a reasonable timeframe.

A candidate pair is considered a definitive match if the alignment achieves $R_{a} > 0.7$ (more than 70% of score notes matched to the performance). This threshold was chosen empirically to ensure a global overlap between the sequences with close score and performed repeat structures. Unmatched notes may correspond to omitted repeats, transcription errors, or specific interpretations. These data are still valuable for performance‑only applications, including large‑scale pre‑training.

Performances that fail to align with the maximal unfolded score are matched to the minimal one, increasing data retention. The exact repeat structure of the performances is not detected. For trills, the number of notes may differ between performances and scores. However, unrollment of trills in the score MIDI yields a higher alignment recall than aligning multiple performed notes to a single base trill note.

Alignments are stored in compressed.npz files compatible with the original MIDI files. Each file contains arrays describing the attributes of the aligned score and performance notes: indices, pitches, and onset/offset times. Insertions and deletions are represented by the sentinel value −1 for missing attributes.

### 3.3 Source performance datasets

PianoCoRe is built by refining and integrating open‑source piano MIDI datasets. This section describes the steps taken to improve the quality of source datasets before combining them under a single collection.

#### 3.3.1 ASAP dataset

The (n)ASAP dataset v2.1.1 (**[Peter et al., 2023](#r38)**) [^5] was used. The original score MIDI files, exported using MuseScore (**[Watson, 2018](#r45)**), contain data‑parsing issues like unrealistic time signatures (e.g., 65/4, 25/32), cut measures with anacrusis, duplicated notes, and notes with zero duration. These were corrected by re‑generating score MIDI files using the standardized pipeline ([Section 3.2.1](#s3_2_1)). The performance MIDI files were cleaned by removing duplicate notes, truncating durations of the first of the two overlapping notes (such that $o_{i} = o_{i - 1} + \hat{d}_{i - 1}$), and removing all notes shorter than 5 ms. There are 208 score and 94 performance MIDI files with zero duration notes in the original dataset.

#### 3.3.2 ATEPP dataset

The ATEPP v1.2 dataset (**[Zhang et al., 2022](#r52)**) [^6] was used. Only 5,091 of 11,674 transcribed performances are paired with scores without an alignment. ATEPP shares the scores with ASAP, but not all suitable scores (e.g., the entirety of Chopin) are present in ATEPP. By matching two datasets, 39 scores from ASAP can be assigned to 827 performances in ATEPP.

As a preprocessing step, score MIDI files were computed from MusicXML files, similar to scores in ASAP. Also, the following metadata issues were corrected: merging duplicate movements under different names (49 movements and 265 reassigned performances), performances with a wrong piece name (24 movements and 43 performances), and performances without a score in the metadata (3 scores and 14 performances). These problems were fixed by matching and checking performances and scores of the same composer.

#### 3.3.3 GiantMIDI‑piano

For GiantMIDI‑Piano (**[Kong et al., 2022](#r25)**), a curated subset of the original data [^7] consisting of 7,236 MIDI files was used. The analysis of the metadata showed duplicates (by YouTube ID) in the original curated data. In total, 315 MIDI transcriptions were distributed under multiple composition names. Also, manual inspection during the matching process revealed other inconsistencies. A MIDI file may represent only a specific movement of the annotated piece, or it may be a performance of a different piece mistakenly matched after a YouTube search.

Since checking and annotating all MIDI files is exhaustive, only sequences that matched with the scores and performances from other examined datasets were used. The final subset included 2,139 performance MIDI files of musical pieces by 402 composers.

#### 3.3.4 PERiScoPe

The PERiScoPe v1.0 dataset (**[Borovik et al., 2025](#r2)**) [^8] was processed by excluding performances from ASAP or ATEPP. Only the remaining 34,773 performance MIDI files transcribed from audio sources using Transkun V2 (**[Yan and Duan, 2024](#r47)**) were used. The dataset required no specific process except for common transcription artifacts, described below in [Section 3.3.6](#s3_3_6).

#### 3.3.5 Aria‑MIDI

From the Aria‑MIDI v1 dataset (**[Bradshaw and Colton, 2025](#r4)**) with 1,186,253 transcribed MIDI files,[^9] 621,132 files that had a composer in the metadata were filtered and used. There are 19,021 unique composer names in the filtered subset.

An important difference in Aria‑MIDI is how sustain pedals are encoded. The transcribed files do not distinguish between pressed and sustained note durations. The durations were predicted as sustained even when the sustain pedal was predicted separately.

#### 3.3.6 Transcription artifacts

One issue fixed for all transcribed MIDI datasets is the error with ‘infinite’ pitches, where notes span until the end of the file. This artifact arises when open‑source transcription models (**[Kong et al., 2021](#r26)**; **[Yan and Duan, 2024](#r47)**) produce unmatched note‑on and note‑off events due to offset or sustain‑pedal decoding errors. During MIDI serialization, such notes remain active till the end of the sequence. An algorithm to identify and correct note durations was developed to repair performances in the source datasets: ATEPP (30 MIDI files), GiantMIDI (9), PERiScoPe (92), and Aria‑MIDI (5,501).

### 3.4 Musical score data sources

To maximize the number of aligned performances, the score library was expanded beyond ASAP and ATEPP and included public domain MusicXML scores from the PDMX dataset (**[Long et al., 2025](#r34)**), originally sourced from MuseScore.[^10] In addition, the sequenced MIDI scores from KunstderFuge [^11] and ClassicalMIDI [^12] websites were used solely for enriching the representation of annotated performed compositions in PianoCoRe. The copyrighted scores are not redistributed in the final dataset. Since KunstderFuge provides live performance and orchestral MIDI files, inexpressive solo piano sequences were filtered out using a Note Onset Median Metric Level (NOMML) heuristic from GigaMIDI (**[Lee et al., 2025](#r29)**). Finally, during the iterative data‑matching process, 421 public domain scores from MuseScore were manually sourced for the most frequently performed compositions that lacked a score.

### 3.5 Data‑combination process

The **PianoCoRe** dataset was assembled using a semi‑automated, iterative process designed to merge multiple sources into a single, structurally unified collection. This process relies on the data matching and note alignment ([Section 3.2](#s3_2)), supplemented by manual curation and labeling to resolve ambiguities.

The main strategy was to establish a unified data organization and gradually integrate scores and performances from source datasets. The combination process unfolds in three stages, illustrated in [Figure 1](#F1):

1. **Core Structure:** The process began with the merging of two foundational datasets: ASAP and ATEPP. Performances and scores from ASAP were matched and reorganized into the unified ATEPP directory structure. Lastly, the 21 ASAP pieces not present in ATEPP were distributed under new directories. This created a unified base of recorded and transcribed performances with their corresponding scores.
2. **Adding Scores:** The core dataset was then augmented by matching its performances against a large corpus of scores from PDMX, KunstderFuge (KDF), and Classical MIDI (CM), along with manually added MuseScore (MS) files.
3. **Adding Performances:** The final step involved the integration of the performance datasets: GiantMIDI‑Piano, PERiScoPe, and Aria‑MIDI. Performances were matched against available scores based on the initial candidate pair selection. If a piece was not present in the dataset, a new directory containing the score and matched performances was added. To further increase data coverage, remaining performances were matched against those without a score from ATEPP and against each other to identify additional composition‑based links.

Figure 1

The three‑stage data matching and annotation pipeline used to create PianoCoRe dataset.

Throughout the process, automated matches were reviewed. For new pieces, composition and movement titles were manually verified and standardized using IMSLP [^13] and web search. This step ensured consistency, corrected mislabeled files, and prevented compositions from being cataloged under different names. To ensure compliance with copyright standards, only works in the public domain in the European Union [^14] were included.

### 3.6 PianoCoRe‑C dataset

The result of the data combination is **PianoCoRe‑C** dataset, where ‘C’ stands for ‘Core’ or ‘Combined’. This dataset represents the most diverse collection of piece‑wise annotated piano performances. It contains 250,046 performance MIDI files for piano pieces composed by 483 composers from different historical periods and styles, ranging Baroque, Classical, and Romantic to Impressionist and Modern. There are 2,869 unique compositions and 5,625 unique pieces and movements. [Figure 2](#F2) highlights the distributions of pieces and performances per piece for popular composers. [Figure 3](#F3) shows the distribution of the number of musical pieces by the number of performances. The median and mean numbers of performances per piece are equal to 8 and 44, respectively. In total, 1,104 musical pieces have 50+ performances samples.

Figure 2

Statistical overview of the **PianoCoRe‑C** dataset for the 50 most represented composers. **Top:** The total number of unique pieces per composer (blue) and the number of pieces with a musical score (light blue). **Bottom:** The average number of performances per piece, accumulated by the MIDI source.

Figure 3

Distribution of the number of musical pieces by the number of performances in PianoCoRe‑C.

Note that **PianoCoRe‑C** is not deduplicated or filtered for quality. This raw, comprehensive collection serves as the foundation for the refined subsets, **PianoCoRe‑B** and **PianoCoRe‑A**, detailed next.

#### 3.6.1 Content and metadata

All score and performance files are organized under the composer/composition/movement/ directory hierarchy, making the dataset easy to navigate and parse. The following unified naming convention is used:

- **Composer**: composer directories follow IMSLP format \[last\_name\],\_\[first\_name\];
- **Piece**: piece/opus numbers are represented using Arabic numbers, scales follow the format \[Note\]\_\[?sharp|flat\]\_\[major|minor\];
- **Filename**: The source of every file is preserved in the metadata and the filename, formatted as \[source\]\_\[original\_filename\].mid.

The dataset provides content and metadata to support various performance analysis and modeling tasks:

- **Score**: MusicXML and MIDI files, source (ASAP, ATEPP, PDMX, or MuseScore), note count;
- **Performance**: MIDI file, source (ASAP, ATEPP, GiantMIDI, PERiScoPe, or Aria), flag for a transcribed performance and transcription model name, performer’s name (if available), duration and note count;
- **Quality Labels**: lead performance (the higher‑priority version of the performance for duplicates), MIDI quality class probabilities and predicted label (‘score’, ‘high quality’, ‘low quality’, ‘corrupted’) ([Section 4](#s4));
- **Alignment**: if available, path to the \_align.npz file with raw alignment (after Parangonar), path to the \_refined\_align.npz file with the complete note‑to‑note alignment between the score and cleaned performance, and alignment recall/precision before and after alignment refinement ([Section 5](#s5)); and
- **Refined Performance**: if alignment is available, refined MIDI file (real and synthetic notes annotated using MIDI markers) that has a complete note alignment with the score MIDI file ([Section 5](#s5)).

#### 3.6.2 Applications

**PianoCoRe‑C** includes matched score and performance MIDI files from the existing piano score and performance datasets: ASAP, ATEPP, PDMX, GiantMIDI‑Piano, Aria‑MIDI, and PERiScoPe. The combined dataset can be used for tasks that benefit from maximum data scale, such as self‑supervised pre‑training of music models, large‑scale music analysis, or developing data cleaning and filtering techniques.

## 4 Performance MIDI Quality Assessment

The **PianoCoRe‑C** dataset contains MIDI files of varying quality, including duplicates. This limits its application to expressive performance modeling. This section details the two‑stage refinement process used to produce **PianoCoRe‑B** (‘B' for ‘Base'), a deduplicated, and quality‑labeled subset of the data.

### 4.1 Content‑based performance deduplication

The dataset combines transcribed piano performance MIDI files from multiple sources. The same performance could appear multiple times, either transcribed by different models or uploaded originally under different titles. Duplicates do not add new information and distort the performance data distribution.

For each piece in **PianoCoRe‑C** with multiple performances, the performances are compared pairwise using a content‑based heuristic developed to detect and cluster identical or nearly identical performances based on close note onsets. Steps are as follows:

1. **Note Representation:** For each MIDI performance, extract all notes, sort them by time, shift timings so the first note starts at zero, and group notes by pitch number.
2. **Pairwise Similarity:** Take two performances $x$ and $z$. For each note $x_{i}$ in $x$ with pitch $p_{i} = p$, find the closest by onset time, matching note $z_{j}$ in $z$ with the same pitch $p_{j} = p$. Then, count the number of note pairs whose absolute time difference is below a threshold $\Delta o_{i j} = \left|\right. o_{i} \left(\right. x \left.\right) - o_{j} \left(\right. z \left.\right) \left|\right. \leq 0.05$ (50 ms, an error bound for a near‑perfect onset prediction accuracy in AMT (**[Kong et al., 2021](#r26)**)). The similarity score is the ratio of close note pairs to the total number of notes in $x$. This score was computed in both directions, from $x$ to $z$ and from $z$ to $x$, and the maximum was taken.
3. **Clustering:** Performances with at least 50% similar (close in time) notes are clustered. One ‘lead’ file is kept, prioritizing the source datasets with fewer performance samples (GiantMIDI $\rightarrow$ ATEPP $\rightarrow$ PERiScoPe $\rightarrow$ Aria‑MIDI) and, when available, alignment recall.

Applying this method flagged 34,452 near‑duplicates, which were removed from the **PianoCoRe‑C** dataset, leaving only lead and unique performances. The duplicates are marked in the metadata.

### 4.2 MIDI quality assessment

Besides duplicates, MIDI files transcribed from audio can vary in quality. Since transcription models are trained on limited ground‑truth data, they often fail in unseen acoustic conditions (**[Edwards et al., 2024](#r10)**; **[Hu et al., 2024](#r19)**). While prior work has proposed perceptually validated metrics (**[Simonetta et al., 2022](#r41)**; **[Ycart et al., 2020](#r48)**) and analytical tools (**[Hu et al., 2024](#r19)**) for evaluating transcriptions, these methods are reference‑based and require ground‑truth data for comparison.

Heuristics such as NOMML (**[Lee et al., 2025](#r29)**) have been used to detect inexpressive MIDI data, but they can struggle with transcriptions. In the experiments, NOMML flagged only 29 performances in PianoCoRe as inexpressive. Transcription artifacts, such as onset jitter, create enough variation to mask a constant tempo, causing score‑like performances to appear expressive.

Not all source MIDI performances in PianoCoRe have corresponding audio or musical scores. To classify each performance, a classifier that assesses MIDI quality directly, independent of score and audio alignment, is trained. The main goal is to detect **corrupted** transcriptions and **score‑like** performances transcribed from audio synthesizing inexpressive scores.

#### 4.2.1 Note alignment and MIDI quality

The initial hypothesis is that a proxy for MIDI quality is its alignment with the score. The analysis began by examining the differences between recorded performances in ASAP and transcribed performances in ATEPP. In ATEPP, 28.3% of sequences are labeled as ‘high quality,’ ‘low quality,’ ‘background noise,’ or ‘corrupted.’ [Figure 4](#F4) visualizes the performances using the note ratio $R_{n} = N_{p} / N_{s}$ and adjusted alignment ratio $R_{a}^{′} = max \left(\right. R_{a} , P_{a} \left.\right)$ ([Section 3.1](#s3_1)). This formulation rewards performances that fully align with the score, even if some segments are not performed.

Figure 4

MIDI performances from ASAP (orange) and ATEPP (blue) grouped by original labels and mapped as a function of performance‑to‑score note ratio $R_{n}$ and adjusted alignment ratio $R_{a}^{′}$.

As we see in [Figure 4](#F4), ‘recorded’ and ‘high quality’ performances cluster in the upper part ($R_{a}^{′} > 0.85$), indicating strong alignment with the scores. In contrast, ‘corrupted’ files are inconsistently scattered, including both well‑ and poorly‑aligned performances, while ‘low quality’ and ‘background noise’ sequences overlap with high‑quality and corrupted transcriptions.

Manual inspection of the MIDI files revealed inconsistencies in the original ATEPP labels. Some ‘low quality’ and ‘unlabeled’ files with poor alignment (e.g., 02709.mid, 03001.mid, 10193.mid) contain clearly broken transcriptions. In contrast, a few files labeled as ‘corrupted’ (e.g., 01591.mid, 05389.mid) align well and are musically usable. Thus, the existing audio‑based labels do not reliably reflect MIDI quality.

#### 4.2.2 MIDI quality training dataset

Based on the analysis of alignments and the adjusted ratio $R_{a}^{′}$, a soft data‑labeling heuristic is proposed. Combined with score and recorded MIDI files the four quality classes are defined as follows:

1. **Score (S):** deadpan score MIDI performances;
2. **High Quality (HQ):** any recorded MIDI, transcribed MIDI with $R_{a}^{′} > 0.9$;
3. **Low Quality (LQ):** transcribed, $0.7 < R_{a}^{′} < 0.85$; and
4. **Corrupted (C):** transcribed, $R_{a}^{′} < 0.65$.

The quality ranges are chosen to be disjoint at the boundaries to create clearer distributions for training.

The heuristic was applied to label the deduplicated performances aligned with musical scores. [Table 2](#T2) shows the distribution of the soft quality labels.

Table 2

Distribution of MIDI quality labels computed using the alignment‑based heuristics for the deduplicated, aligned performances in PianoCoRe‑B.

| HQ | LQ | C | No Label |
| --- | --- | --- | --- |
| 170,312 | 4,545 | 140 | 40,597 |

These data were used to sample subsets for training, testing, and calibration. To ensure composition leakage, a piece‑based split was applied, maximizing the number of the real corrupted samples in the test set. Second, to create a diverse dataset, there are no more than three samples for each musical piece from each data source (ASAP, ATEPP, PERiScoPe, and Aria‑MIDI), as well as a soft quality label (HQ, LQ, and C).

As seen in [Table 2](#T2), LQ and C soft labels are underrepresented. For training, 2,500, 1,000, and 86 real HQ, LQ, and C samples, respectively, are balanced with synthetic performances built from the sampled HQ MIDI files. The artificial corruptions for LQ/C classes included random note removal (15%–25%/35%–50%), onset/offset jitter (up to 20 ms/150 ms), velocity jitter (up to 5/20 bins), and random note insertions (up to 5%/30%). Similarly, 953 real scores were augmented with 1,447 synthetic versions (randomized constant velocities, 10‑ms onset jitter) to simulate transcription artifacts for score‑based audio.

For validation and testing, 200 real Score HQ, and LQ samples are selected alongside 54 Corrupted performances. The classifier calibration set includes all of the real samples from the evaluation split, with no more than three samples per piece, source, and class. The class distributions per each set are shown in [Table 3](#T3).

Table 3

MIDI quality classification dataset splits.

|  | S | HQ | LQ | C |
| --- | --- | --- | --- | --- |
| training | 2,500 | 2,500 | 2,500 | 2,500 |
| real | 953 | 2,500 | 1,000 | 86 |
| synth | 1,547 | 0 | 1,500 | 2,414 |
| test | 200 | 200 | 200 | 54 |
| calibration | 662 | 6,525 | 893 | 54 |

#### 4.2.3 MIDI quality classifier

The data representation consists of a stacked sequence encoding with five note features: Pitch, TimeShift (s), Velocity (MIDI bins), Duration (s), and absolute TimePosition (s). This encoding does not contain any score features (beat positions and durations) to make the model score‑agnostic and universal.

The backbone is a 12‑layer transformer encoder (**[Vaswani et al., 2017](#r44)**) with 80 million parameters, pre‑trained using a multi‑mask language modeling objective (**[Borovik et al., 2025](#r2)**). The model dimension is set to 768, and self‑attention is extended with Rotary positional embeddings (**[Su et al., 2024](#r42)**). Real‑valued note features are passed to sinusoidal embeddings (**[Guo et al., 2023](#r15)**) for lossless encoding. For classification, penultimate‑layer embeddings are prepended with a \[CLS\] token and processed by a one‑layer transformer (dimension 128) and a classification head.

The pre‑training was conducted on the deduped subset of Aria‑MIDI (**[Bradshaw and Colton, 2025](#r4)**) with 371,053 diverse piano MIDI files, provided with the official dataset release. The maximum context length is set to 512 notes. The pre‑training included 600,000 steps with batch size 128, while the fine‑tuning took 20,000 steps with batch size 512. Training data augmentation included pitch shift ($\pm 6$ semitones), velocity shift ($\pm 6$ MIDI bins), and tempo stretching ($\pm 5 \%$).

The trained MLM backbone was verified on emotion and pianist classification tasks. On the EMOPIA dataset (**[Hung et al., 2021](#r22)**), the classifier achieved a test accuracy of 72.7% and an F1 score of 72.1%. On the Pianist8 dataset (**[Chou et al., 2024](#r8)**), the accuracy and F1 score were 86.4% and 85.5%. The metrics are close to similarly sized models (**[Liang et al., 2024](#r31)**) and slightly below those of larger models (**[Bradshaw et al., 2025](#r5)**).

#### 4.2.4 Results

[Table 4](#T4) shows the evaluation results of the classifier configurations tested on the balanced test set.

Table 4

Evaluation of MIDI quality classifiers using F1 scores. Best scores in **bold**. no synth—no synthetic training data, mean—mean pooling (no \[CLS\]), no TL—no transformer layer before the classifier head, no MLM—token embeddings and classifier only. The last block shows feature‑masking ablations.

| Model | S | HQ | LQ | C | Avg. |
| --- | --- | --- | --- | --- | --- |
| base | **1.000** | **0.839** | 0.777 | **0.946** | **0.891** |
| no synth | **1.000** | 0.759 | **0.778** | **0.946** | 0.871 |
| mean | **1.000** | 0.828 | 0.752 | 0.881 | 0.865 |
| mean, no TL | 0.993 | 0.802 | 0.713 | 0.851 | 0.840 |
| no MLM | 0.995 | 0.773 | 0.667 | 0.842 | 0.819 |
| mask Pitch | **1.000** | 0.803 | 0.723 | 0.913 | 0.860 |
| mask Timing | 0.990 | 0.788 | 0.747 | 0.851 | 0.844 |
| mask Velocity | **1.000** | 0.834 | 0.776 | 0.893 | 0.876 |

The best configuration achieved a macro F1 score of 89.1% on the held‑out test set. It learned to perfectly distinguish score‑like MIDI files and showed less errors between HQ, LQ, and C classes. The synthetic training samples and token‑based aggregation helped to learn more robust decision boundaries. Masking of note features revealed the shared contribution of pitch, dynamic, and timing to MIDI quality classification. Since note‑level alignment is imperfect and quality is continuous rather than discrete, errors on the test set are expected.

### 4.3 Classifying the PianoCoRe‑C dataset

The best‑performing classifier was taken and calibrated on the held‑out calibration set ([Table 3](#T3)). To maximize recall, the sequences are labeled as Corrupted or Score, if the classifier was activated in at least one segment ($p_{S} > 0.3$ or $p_{C} > 0.3$). For the LQ class, a conservative threshold of $p_{LQ} > 0.75$, which does not categorize half of the data as low quality, was chosen. Note that HQ and LQ labels are advisory, as ‘low quality' MIDI files may be suitable for certain applications. However, the files labeled as Corrupted or Score are, in most cases, indeed either broken or were transcribed from rendered musical scores with constant tempo and/or dynamics. It is better to filter them during piano‑expression analysis.

The final distribution of MIDI quality labels in the PianoCoRe‑C dataset is shown in [Table 5](#T5).

Table 5

PianoCoRe dataset and its source subsets labeled by the MIDI quality classifier.

| Source | S | HQ | LQ | C |
| --- | --- | --- | --- | --- |
| ASAP | 0 | 1,066 | 0 | 0 |
| ATEPP | 0 | 10,231 | 900 | 433 |
| GiantMIDI | 11 | 2,071 | 52 | 5 |
| PERiScoPe | 82 | 34,596 | 91 | 4 |
| Aria‑MIDI | 1,151 | 180,977 | 18,359 | 17 |
| PianoCoRe | 1,244 | 228,941 | 19,402 | 459 |

### 4.4 PianoCoRe‑B dataset

By applying the deduplication and quality assessment models to **PianoCoRe‑C** dataset, we obtain **PianoCoRe‑B**. The filtered subset consists of 214,092 deduplicated performance MIDI not classified as Corrupted or Score. There are 5,591 musical pieces composed by 478 composers ([Table 1](#T1)).

#### 4.4.1 Applications

**PianoCoRe‑B** is designed for tasks that depend on large amounts of clean and reliable piano performance data. Specifically, this dataset is useful for large‑scale, self‑supervised pre‑training; musical analysis of performance styles; and piano performance generation.

## 5 Refined Note Alignment

Piano‑expression modeling tasks require precise note‑level alignment between scores and performances. The **PianoCoRe‑A/A\*** subsets (‘A' for ‘Aligned') consist of all performance MIDI files that are temporally aligned to scores. Two forms of alignment are considered:

1. **Raw Alignments:** processed output of Parangonar, containing matches, insertions, and deletions between score and performance notes and
2. **Refined Alignments:** raw alignments, refined using the **RAScoP** pipeline, which cleans and completes initial matches.

### 5.1 Raw note alignment challenges

A direct output from note aligners like Parangonar (**[Peter, 2023](#r37)**) or Nakamura's alignment tool (**[Nakamura et al., 2017](#r36)**), while powerful, is sometimes insufficient for direct use in generative models. Raw alignments can suffer from issues, illustrated in [Figure 5](#F5):

- **Temporal Discontinuities:** Incorrect alignment links that cross in time or match musically distant notes, leading to unrealistic tempo fluctuations and high inter‑onset timing deviations;
- **Alignment Holes:** Continuous regions of unaligned notes in the score or performance, often caused by skipped repeats or transcription errors.

Figure 5

Real‑world alignment challenges motivating the RAScoP pipeline. **Top:** local timing errors (crossed links) and missing/extra notes. **Bottom:** large structural deviation from a missing score segment, causing incorrect links. Other performed notes remain usable. Alignments were computed with Parangonar.

Some performance rendering models were trained only on a subset of aligned score and performance notes with incomplete score contexts (**[Rhyu et al., 2022](#r39)**; **[Tang et al., 2025](#r43)**; **[Zhang et al., 2024](#r51)**). Other models removed timing outliers (**[Jeong et al., 2019a](#r23)**; **[Xia, 2016](#r46)**) and interpolated missing notes (**[Borovik and Viro, 2023](#r3)**; **[Borovik et al., 2025](#r2)**). However, these processes are not available as easy‑to‑use tools.

A configurable algorithm was designed to create a parallel score and performance dataset by cleaning evident outliers and interpolating notes for which no performance counterpart exists. Specifically, this algorithm addresses two main problems:

- **Timing Errors:** remove large inter‑ and intra‑onset deviations and implied unrealistic tempi and
- **Missing Notes:** fill in the unperformed notes to have complete performed score contexts.

The following section describes this algorithm.

### 5.2 Alignment cleaning and refinement

**RAScoP** (‘Refined Alignment for Scores and Performances’) is an integrated pipeline designed to take a raw score–performance alignment and transform it into a clean, complete, and temporally coherent parallel score–performance data pair. The algorithm analyzes and refines the alignment through four sequential steps, illustrated in [Figure 6](#F6):

1. **(****H****):** alignment hole processing,
2. **(****O****)**: onset cleaning and temporal refinement,
3. **(****I****):** note interpolation, and
4. **(****S****):** performance‑to‑score synchronization.

Figure 6

Note‑level alignment and the RAScoP pipeline for alignment refinement. The processing steps are demonstrated using an artificial example containing all types of errors. Score notes are drawn in black and performance notes are drawn in blue and green.

#### 5.2.1 Alignment hole processing

The first step detects and removes large, structurally incorrect alignment sections. An ‘alignment hole' is defined as a continuous region of notes where the alignment is sparse or nonsensical (only a few notes are aligned). In scores, the holes correspond to unperformed score measures (e.g., repeats), whose individual notes may be incorrectly matched with random performance notes. In the performances, the holes are the extra performed segments whose notes may be inadvertently aligned with random score notes.

To detect holes, a sliding window approach is used. Let $H_{a}$ be a ratio of unaligned notes within a surrounding window of $H_{w}$ notes for a given note. If $H_{a}$ ratio exceeds a threshold $H_{r}$, the note is flagged. Contiguous regions of flagged notes are designated as holes, and all alignment pairs within them are removed.

The default values are $H_{w} = 31$ notes and $H_{r} = 0.75$. The window size is close to double the median (15) and mean (16.9) number of notes in a measure in all scores in the dataset. With this window, we consider on average one measure to the left and one to the right. Setting the threshold at $75 \%$ ensures that only regions that are almost entirely unaligned are removed.

#### 5.2.2 Onset cleaning and temporal refinement

This stage refines the temporal alignment of concurrently played notes (chords) and corrects large‑scale time shifts. First, all aligned notes are used to build the initial onset pair list: tuples of score onset beat $o_{i}$ and the average performed onset time $t \left(\right. o_{i} \left.\right)$ for all notes in the chord. Then, note and onset times are checked for misalignments and outliers based on:

- high intra‑onset deviations and
- inter‑onset intervals that deviate from the local performance tempo.

For intra‑onset deviations, the onset deviations $\Delta t_{i} \left(\right. n_{j} \left.\right) = t \left(\right. n_{j} \left.\right) - t \left(\right. o_{i} \left.\right)$ from $t \left(\right. o_{i} \left.\right)$ are computed for all notes $n_{j}$ in a chord: $\left{\right. n_{j} \left|\right. o \left(\right. n_{j} \left.\right) = o_{i} \left.\right}$. By default, notes whose onsets deviate from $t \left(\right. o_{i} \left.\right)$ by more than two standard deviations are removed from the alignment as outliers. For chords with two distant notes, both notes will be removed if the condition is met.

For inter‑onset intervals, the method estimates the maximum and minimum plausible time shifts $\Delta t_{max} \left(\right. o_{i} \left.\right)$ and $\Delta t_{min} \left(\right. o_{i} \left.\right)$ between the current and previous score onsets $o_{i}$ and $o_{i - 1}$. If the time interval between the current and previous onset implies a tempo outside a plausible range (by default, 15–480 BPM), it is identified as an alignment jump. This onset can be filtered out of the alignment. However, by default, the timing of the notes of the affected onsets is adjusted.

First, a local tempo $\tau_{local} \left(\right. o_{i} \left.\right)$ is estimated based on a $w$ ‑second window (by default, $w = 8$) of preceding performed note onsets $O_{local} \left(\right. o_{i} \left.\right) = \left{\right. o_{j} \left|\right. t \left(\right. o_{i} \left.\right) - t \left(\right. o_{j} \left.\right) < w \left.\right}$. Then, the expected onset time $\hat{t} \left(\right. o_{i} \left.\right)$ is computed using the inter‑onset beat shift $IOI_{i}^{s} = o_{i} - o_{i - 1}$ and $\tau_{local} \left(\right. o_{i} \left.\right)$. Using the expected onset time, the required time shift $\Delta t_{adj} \left(\right. o_{i} \left.\right) = \hat{t} \left(\right. o_{i} \left.\right) - t \left(\right. o_{i} \left.\right)$ is determined, and the subsequent performance notes are shifted accordingly.

This step explicitly alters the global timing in the original performance MIDI. However, after the shift, the onsets fall into the range of the plausible local tempos, and tempo outliers are not learned by the trained models. Any unperformed notes can be also naturally filled in with the same local performance tempo.

In addition, close onset pairs with $\Delta t \left(\right. o_{i} \left.\right) = t \left(\right. o_{i} \left.\right) - t \left(\right. o_{i - 1} \left.\right) < 0.01$ (10 ms) are filtered out to avoid two same‑pitch note‑on events (which is impossible for a human performer). After the alignment hole processing and onset cleaning, the algorithm cleans up the performance MIDI by removing notes without a link in the alignment. In the end, only matched and cleanly performed notes remain.

#### 5.2.3 Note interpolation

This step interpolates the unperformed notes to create parallel note‑aligned score–performance pairs.

The note onset time $t \left(\right. n_{i} \left.\right)$ of a note $n_{i}$ is linearly interpolated from two neighboring performed notes $n_{j}$ and $n_{k}$. To avoid the contribution of very close notes, the configurable minimum beat and time intervals $n_{j}$ and $n_{k}$ between the two anchor notes are used ($t \left(\right. n_{k} \left.\right) - t \left(\right. n_{j} \left.\right) \geq \Delta t_{int}$ and $o \left(\right. n_{k} \left.\right) - o \left(\right. n_{j} \left.\right) \geq \Delta o_{int}$).

Note articulation (duration) and dynamics (MIDI velocity) are averaged and weighted by the performed notes in the neighboring beats. The weights are inversely proportional to the absolute beat distances $IOI_{i , j}^{s} = \left|\right. o \left(\right. n_{j} \left.\right) - o \left(\right. n_{i} \left.\right) \left|\right.$ from the score position of the note $n_{i}$ being interpolated. Closer notes contribute a higher weight to the interpolated features.

The algorithm prevents the creation of notes with identical pitch and onset, and shortens overlapping notes so that at each new key press the previous note is closed. The result is a performance MIDI file fully aligned with the score at the note level. Interpolated notes are marked with a special MIDI text marker, allowing them to be filtered out or marked during model training.

#### 5.2.4 Performance–score synchronization

This step synchronizes the beat structure of the refined performance MIDI with the score. This data format is commonly used in MIDI encodings with beat/bar tempo (**[Huang and Yang, 2020](#r21)**; **[Hsiao et al., 2021](#r18)**; **[Zeng et al., 2021](#r50)**). The alignment pairs are used to compute a beat‑to‑time mapping and insert inter‑beat tempo changes into the performance MIDI. For example, for a 4/4 time signature and 480 ticks per quarter, notes at the beats are separated by 480 ticks in both the score and performance MIDI, with exact times derived from tempo changes.

Finally, the entire performance is shifted so that its first played note occurs at the same time as the first score note, ensuring a consistent starting point for all performances of the same composition.

#### 5.2.5 Final output

The algorithm returns the refined alignment, refined performance MIDI, and note‑level alignment recall ratios. The recall values from different stages (initial, hole processing, and onset cleaning) serve as quantitative indicators of alignment quality and can be used to interrupt the refinement process. The alignment is released as a compressed.npz file containing an array of performance note indices aligned to the sorted score MIDI notes, along with a boolean mask for interpolated notes. All MIDI processing steps are performed using the symusic Python library (**[Liao et al., 2024](#r32)**).

The presented refinement does not rematch links produced by the note aligner. It only filters existing links and interpolates missing notes. Each step of the pipeline can be enabled independently. Default parameters were chosen empirically rather than optimized, as automated evaluation would require precise human annotations. Custom clean datasets can be generated using the released raw alignments and MIDI files.

In PianoCoRe, all refined performance MIDI files underwent the first three stages of the RAScoP alignment and the final initial performance onset shift. Beat synchronization was not applied in order to preserve the original timing without re‑quantizing the note onsets and offsets. Synchronization can be computed using the refined score MIDI, performance MIDI, and note‑level alignment.

### 5.3 Refinement quality evaluation

To quantitatively demonstrate the effectiveness of **RAScoP**, the trade‑off between alignment temporal integrity (the distribution of intra‑ and inter‑onset deviations) and alignment recall ($R_{a}$) is evaluated.

The benefit of alignment refinement is shown in [Figure 7](#F7). Applying the full pipeline (H + O) significantly reduces the standard deviation of inter‑onset deviations within chords, indicating cleaner note timing patterns. Furthermore, the distribution of beat tempos becomes more stable and centered around a musically plausible range, as the algorithm corrects for the extreme tempo values implied by raw, noisy alignments.

Figure 7

Distribution of inter‑onset deviations and beat tempos for alignments before processing (‑), after hole processing (H), after onset cleaning (O), and after both hole and onset cleaning (H + O).

[Table 6](#T6) quantifies the ‘cost' of the cleaning process in terms of alignment recall. The performances are grouped from higher to lower recall. Overall, the average recall $\overset{―}{R}_{a}$ decreases by a modest 1.5% (from 0.935 to 0.920), with the Onset Cleaning stage (O) contributing most to this reduction. The cleaning process primarily affects the highest‑quality alignments ($\overset{―}{R}_{a} > 0.95$), reducing their share from 54.3% to 42.9%. These sequences are not discarded but rather migrate to the still‑high‑quality lower bands. After refinement, the majority of sequences (86.6%) still maintain a high alignment recall of over 85%. The loss of a few alignment links is an acceptable price for the improvement in the temporal quality of the performance data.

Table 6

Mean alignment recall $\overset{―}{R}$ after different alignment refinement stages and the ratio of sequences (%) inside different recall bands.

<table width="100%"><thead><tr><th align="left"></th><th align="center" colspan="2">Raw</th><th align="center" colspan="2">After H</th><th align="center" colspan="2">After H+O</th></tr><tr><th align="left">Band</th><th align="center"><math><msub><mrow><mover><mrow><mi>R</mi></mrow> <mo>―</mo></mover></mrow> <mrow><mi>A</mi></mrow></msub></math></th><th align="center">%</th><th align="center"><math><msub><mrow><mover><mrow><mi>R</mi></mrow> <mo>―</mo></mover></mrow> <mrow><mi>H</mi></mrow></msub></math></th><th align="center">%</th><th align="center"><math><msub><mrow><mover><mrow><mi>R</mi></mrow> <mo>―</mo></mover></mrow> <mrow><mi>H</mi> <mo>+</mo> <mi>O</mi></mrow></msub></math></th><th align="center">%</th></tr></thead><tbody><tr><td align="left">0.95–1.00</td><td align="center">0.975</td><td align="center">54.3</td><td align="center">0.975</td><td align="center">53.9</td><td align="center">0.973</td><td align="center">42.9</td></tr><tr><td align="left">0.90–0.95</td><td align="center">0.929</td><td align="center">26.6</td><td align="center">0.929</td><td align="center">26.7</td><td align="center">0.928</td><td align="center">30.4</td></tr><tr><td align="left">0.85–0.90</td><td align="center">0.879</td><td align="center">10.1</td><td align="center">0.878</td><td align="center">10.0</td><td align="center">0.878</td><td align="center">13.3</td></tr><tr><td align="left">0.80–0.85</td><td align="center">0.828</td><td align="center">4.7</td><td align="center">0.828</td><td align="center">4.6</td><td align="center">0.828</td><td align="center">6.5</td></tr><tr><td align="left">0.75–0.80</td><td align="center">0.779</td><td align="center">2.1</td><td align="center">0.778</td><td align="center">2.2</td><td align="center">0.777</td><td align="center">3.2</td></tr><tr><td align="left">0.70–0.75</td><td align="center">0.725</td><td align="center">1.1</td><td align="center">0.727</td><td align="center">1.0</td><td align="center">0.728</td><td align="center">1.6</td></tr><tr><td align="left">0.60–0.70</td><td align="center">0.660</td><td align="center">0.7</td><td align="center">0.663</td><td align="center">1.1</td><td align="center">0.661</td><td align="center">1.5</td></tr><tr><td align="left">0.00–0.60</td><td align="center">0.471</td><td align="center">0.4</td><td align="center">0.464</td><td align="center">0.5</td><td align="center">0.462</td><td align="center">0.6</td></tr><tr><td align="left">all</td><td align="center">0.935</td><td align="center">100.0</td><td align="center">0.934</td><td align="center">100.0</td><td align="center">0.920</td><td align="center">100.0</td></tr></tbody></table>

### 5.4 PianoCoRe‑A dataset

Applying this pipeline to the files from **PianoCoRe‑B** yields the final aligned datasets. **PianoCoRe‑A** contains 157,207 cleaned and note‑aligned sequences from **PianoCoRe‑B** for 1,591 pieces written by 151 composers, totaling 12,509 hours of music ([Table 1](#T1)).

The performances can be filtered out for any applications based on the alignment ratio. For tasks that demand the highest possible data fidelity, **PianoCoRe‑A\*** is introduced. This is a high‑confidence subset of **PianoCoRe‑A** containing High Quality MIDI files with at least 85% of aligned notes. **PianoCoRe‑A\*** consists of 130,275 performances for 1,517 pieces.

#### 5.4.1 Applications

**PianoCoRe‑A/A\*** represent a large‑scale resource of score–performance–aligned piano MIDI data. They pave the way for training more nuanced models for rendering expressive piano performances without having to perform rigorous data matching and alignment.

## 6 Music Performance Rendering

The PianoCoRe dataset is validated on a downstream task of expressive piano performance rendering. The hypothesis is that the scale, diversity, and targeted refinement of the **PianoCoRe‑A** dataset enable the training of more accurate performance models compared to baselines trained on smaller or uncleaned data subsets.

### 6.1 Experimental setup

The experiments used PianoFlow (**[Borovik et al., 2025](#r2)**), a model for symbolic music performance rendering based on conditional flow matching (**[Lipman et al., 2022](#r33)**). It employs an encoder transformer to inpaint masked performance features $x_{\text{m}}$ (TimeShift, Velocity, TimeDuration, TimeDurationSustain) given score features $y$ (Pitch, Position, PositionShift, and Duration) and performance context $x_{\text{ctx}}$. As Aria‑MIDI does not distinguish between pressed and sustained notes, only seven features without TimeDuration were used. The base configuration (8 layers, 24 million parameters) was adopted, and a learned embedding was added to interpolated notes, as in the original model.

The model was trained on subsets of aligned and cleaned performances from PianoCoRe‑A: ASAP, ASAP+ATEPP, ASAP+ATEPP+PERiScoPe, and the full dataset. Performances with fewer than 85% aligned notes ($R_{RAScoP} < 0.85$) were removed to retain more real played notes. For ablation, models were trained on all PianoCoRe‑A performances ($R_{RAScoP} \geq 0.7$) and a version of the dataset without the hole and onset cleaning from RAScoP pipeline (raw alignments plus note interpolation). Data were split by composition into 90%/10% for training/evaluation, all movements and performances of a piece appeared in only one split.

### 6.2 Results

#### 6.2.1 Training convergence

[Figure 8](#F8) illustrates the feature‑based validation losses tracked during training. Each model was evaluated on a validation set drawn from the same source data (e.g., the ‘ASAP+ATEPP’ model on unseen ‘ASAP+ATEPP’ performances). The results reveal a pattern: the model trained only on ‘ASAP’ quickly overfits, demonstrating that a small dataset, even of high quality, is insufficient. As the scale of the data increases (‘+ATEPP’, ‘+PERiScoPe’), overfitting is delayed.

Figure 8

Validation loss curves for PianoFlow trained on different subsets of the data. Larger and refined training datasets reduce overfitting in the long run.

The comparison between the ‘PianoCoRe‑A’ model (blue) and its unrefined counterpart ‘w/o RAScoP’ (gray) provides direct evidence of the value of the refinement pipeline. The refined dataset yields a more stable and consistently lower validation loss, particularly for the note time shifts. This confirms that targeted removal of temporal noise is crucial for learning an accurate timing model.

#### 6.2.2 Unconditional generation

This section presents the evaluation results for the unconditional performance rendering. The inference set included test set scores with at least three performances from two different MIDI sources (e.g., ASAP and Aria‑MIDI). The models rendered each score in its entirety seven times. Pearson correlation (**[Borovik and Viro, 2023](#r3)**; **[Jeong et al., 2019b](#r24)**; **[Zhang et al., 2024](#r51)**) between the note features of the dataset and rendered performances was computed. The evaluated features are: onset velocity (Vel), relative inter‑onset intervals (IOI), relative intra‑onset deviations (OD), and note articulation (Art).

[Table 7](#T7) presents the mean Pearson correlation between the model outputs and the ground‑truth performances from a multi‑source test set. Models trained on more diverse datasets (‘+ ATEPP’, ‘+ PERiScoPe’, and ‘PianoCoRe‑A') consistently outperform the baseline trained only on ‘ASAP’. Interestingly, the model trained on ASAP and ATEPP shows higher correlation with an average set of performances from PianoCoRe‑A. This may be because ATEPP specifically focuses on the performances of renowned pianists. Other datasets contain a wider variety of performance styles.

Table 7

Correlation between the features of the rendered and PianoCoRe‑A performances. First row—intra‑set correlations, other rows—models trained on different data subsets. Vel—velocity, IOI—inter‑onset‑interval, OD—relative onset deviation, Art—sustained articulation. The best scores are in **bold**.

|  | Vel | IOI | OD | Art |
| --- | --- | --- | --- | --- |
| Dataset | 0.57±0.19 | 0.90±0.06 | 0.22±0.17 | 0.44±0.19 |
| ASAP | 0.37±0.17 | 0.83±0.11 | 0.07±0.15 | 0.28±0.13 |
| \+ ATEPP | **0.42** ± **0.16** | 0.85±0.11 | **0.12** ± **0.14** | 0.35±0.15 |
| \+ PERiScoPe | 0.41±0.17 | **0.86** ± **0.11** | 0.11±0.17 | **0.36** ± **0.17** |
| **PianoCoRe‑A** | 0.40±0.17 | **0.86** ± **0.11** | 0.10±0.17 | 0.35±0.17 |
| $R_{RAScoP} \geq 0.7$ | 0.39±0.16 | 0.85±0.11 | 0.09±0.16 | 0.35±0.18 |
| w/o RAScoP | 0.41±0.16 | 0.85±0.11 | 0.09±0.16 | **0.36** ± **0.18** |

More training data with more interpolated notes ($R_{RAScoP} \geq 0.7$) slightly hurts the unconditional rendering capabilities. The model trained on raw data without the cleanup shows lower correlation with higher quality performances for note timing (IOI and OD).

#### 6.2.3 Performance continuation

The final analysis evaluated the models in a performance continuation task across four distinct test domains: ASAP, ATEPP, PERiScoPe, and Aria. As in the previous experiments, compositions and performances were not seen during the training. The models performed 256 notes in parallel using the performance context of the preceding 256 notes. [Table 8](#T8) shows the mean absolute error computed against the ground truth performance features.

Table 8

Conditional performance rendering (performance continuation) results across training subsets and unseen source sequences. Size denotes the training set size. Vel—Velocity (MIDI bins), TS—TimeShift (s), TD—TimeDurationSustain (s). Lower is better; best values are in **bold**.

<table width="100%"><thead><tr><th align="left"></th><th align="left"></th><th align="center" colspan="3">ASAP</th><th align="center" colspan="3">ATEPP</th><th align="center" colspan="3">PERiScoPe</th><th align="center" colspan="3">Aria‑MIDI</th></tr><tr><th align="left">Dataset</th><th align="center">Size</th><th align="center">Vel</th><th align="center">TS</th><th align="center">TD</th><th align="center">Vel</th><th align="center">TS</th><th align="center">TD</th><th align="center">Vel</th><th align="center">TS</th><th align="center">TD</th><th align="center">Vel</th><th align="center">TS</th><th align="center">TD</th></tr></thead><tbody><tr><td align="left">ASAP</td><td align="center">1 k</td><td align="center">9.885</td><td align="center">0.023</td><td align="center">0.187</td><td align="center">9.928</td><td align="center">0.022</td><td align="center">0.206</td><td align="center">9.893</td><td align="center">0.023</td><td align="center">0.230</td><td align="center">9.957</td><td align="center">0.027</td><td align="center">0.275</td></tr><tr><td align="left">+ ATEPP</td><td align="center">6 k</td><td align="center">9.157</td><td align="center">0.017</td><td align="center">0.168</td><td align="center">8.230</td><td align="center">0.015</td><td align="center">0.191</td><td align="center">8.782</td><td align="center">0.016</td><td align="center">0.216</td><td align="center">8.721</td><td align="center">0.019</td><td align="center">0.252</td></tr><tr><td align="left">+ PERiScoPe</td><td align="center">25 k</td><td align="center">8.851</td><td align="center"><strong>0.016</strong></td><td align="center"><strong>0.154</strong></td><td align="center"><strong>7.888</strong></td><td align="center"><strong>0.013</strong></td><td align="center"><strong>0.189</strong></td><td align="center">8.117</td><td align="center"><strong>0.015</strong></td><td align="center"><strong>0.192</strong></td><td align="center">8.133</td><td align="center"><strong>0.017</strong></td><td align="center">0.230</td></tr><tr><td align="left"><strong>PianoCoRe‑A</strong></td><td align="center">124 k</td><td align="center"><strong>8.613</strong></td><td align="center"><strong>0.016</strong></td><td align="center">0.155</td><td align="center">7.967</td><td align="center">0.014</td><td align="center">0.194</td><td align="center">8.094</td><td align="center"><strong>0.015</strong></td><td align="center">0.194</td><td align="center"><strong>7.872</strong></td><td align="center"><strong>0.017</strong></td><td align="center"><strong>0.205</strong></td></tr><tr><td align="left">  <math><msub><mi>R</mi> <mrow><mrow><mi>RAScoP</mi></mrow></mrow></msub> <mo>≥</mo> <mn>0.7</mn></math></td><td align="center">141 k</td><td align="center">8.631</td><td align="center"><strong>0.016</strong></td><td align="center">0.158</td><td align="center">7.944</td><td align="center">0.014</td><td align="center">0.196</td><td align="center"><strong>8.071</strong></td><td align="center"><strong>0.015</strong></td><td align="center">0.194</td><td align="center">7.921</td><td align="center"><strong>0.017</strong></td><td align="center">0.206</td></tr><tr><td align="left"> w/o RAScoP</td><td align="center">124 k</td><td align="center">8.734</td><td align="center">0.017</td><td align="center">0.159</td><td align="center">8.059</td><td align="center">0.015</td><td align="center">0.193</td><td align="center">8.199</td><td align="center">0.016</td><td align="center">0.196</td><td align="center">8.055</td><td align="center">0.018</td><td align="center">0.211</td></tr></tbody></table>

The results complement the previous findings. With more training data, the model performs better on MIDI files of different sources. PianoCoRe‑A achieves the best average performance on ASAP and Aria‑MIDI performances and second‑best results on the other subsets. Only the model trained on data without overrepresented Aria‑MIDI achieves similar or lower errors on ATEPP and PERiScoPe. Given the validation loss plots in [Figure 8](#F8), the full dataset model has room for an improvement in the long run. Overall, the results show the potential of PianoCoRe for training performance models robust to varying piano data distributions.

### 6.3 Future work

A subjective listening test of popular models trained on the subsets of PianoCoRe dataset would be a valuable next step to confirm that objective improvements translate to human perception. Since performances from Aria‑MIDI dominate PianoCoRe, a more balanced sampling of performances per source might provide a better generalization to all source data domains. Fine‑tuning on high‑fidelity subsets, such as ASAP, could potentially improve performance even further.

## 7 Limitations

Despite rigorous curation, PianoCoRe has limitations. There are no duplicate musical pieces with different names. However, an error margin of 1% is reserved for potential movement‑level naming errors that were inherited from the source datasets. Furthermore, the dataset distribution remains skewed toward Western classical repertoire and popular composers, reflecting the biases of the underlying open‑source corpora.

The dataset relies on open‑source MusicXML scores and automated alignment. MusicXML scores are not error‑free and may also include a segment of a complete written musical composition. Since it is difficult to validate large‑scale datasets precisely, any errors in the source notations may propagate to the downstream applications. Also, due to the iterative combination of source datasets, fewer than 1% of performances may contain neighboring movements or differ from the scores by more than twice the length. It is recommended to use composition‑wise splits in the applications using the dataset.

The classifier‑based MIDI quality labels were calibrated for recall in the corrupted and score‑like classes to filter out incorrect and inexpressive data. The labels do not guarantee perfect alignment with human expectations. During note interpolation, RAScoP may introduce deadpan performance note segments that must be addressed by downstream applications. Additionally, interpolation does not handle sustain pedal effects. A better solution would be to predict missing notes and pedals using a trained model.

## 8 Conclusion

This article presented **PianoCoRe**, a unified, large‑scale piano MIDI dataset created by combining, refining, annotating, and aligning existing open‑source corpora. Released in tiered subsets, PianoCoRe supports a wide spectrum of tasks: from performance analysis and large‑scale pre‑training to expressive piano performance rendering and score‑to‑performance translation. The dataset enables reproducible research by allowing researchers to create non‑overlapping data splits across previously isolated datasets.

To ensure data integrity, two challenges were addressed: the quality of performance MIDI and note‑level alignments. A classifier was trained to identify deadpan and corrupted MIDI transcriptions, and an alignment refinement pipeline was designed to remove temporal outliers in aligned score‑performance data. The experiments showed that the model trained on these refined subsets benefits from the increased repertoire diversity and cleaner note features.

Future directions include extending the methodology to multi‑instrument repertoires, developing more robust quality assessment models and incorporating more granular score and performance annotations. By making PianoCoRe openly available, the goal is to establish a foundation for advancing symbolic music performance modeling and analysis research.

## Notes

1. [https://github.com/ilya16/PianoCoRe](https://github.com/ilya16/PianoCoRe)
2. [https://doi.org/10.5281/zenodo.19186016](https://doi.org/10.5281/zenodo.19186016)
3. [https://huggingface.co/datasets/SyMuPe/PianoCoRe](https://huggingface.co/datasets/SyMuPe/PianoCoRe)
4. [https://github.com/CPJKU/asap-dataset](https://github.com/CPJKU/asap-dataset)
5. [https://github.com/tangjjbetsy/ATEPP](https://github.com/tangjjbetsy/ATEPP)
6. [https://github.com/bytedance/GiantMIDI-Piano](https://github.com/bytedance/GiantMIDI-Piano)
7. [https://huggingface.co/datasets/SyMuPe/PERiScoPe](https://huggingface.co/datasets/SyMuPe/PERiScoPe)
8. [https://huggingface.co/datasets/loubb/aria-midi](https://huggingface.co/datasets/loubb/aria-midi)
9. [https://musescore.com/sheetmusic](https://musescore.com/sheetmusic)
10. [https://kunstderfuge.com](https://kunstderfuge.com/)
11. [https://www.classicalmidi.co.uk](https://www.classicalmidi.co.uk/)
12. [https://imslp.org](https://imslp.org/)
13. [https://eur-lex.europa.eu/EN/legal-content/summary/copyright-and-related-rights-term-of-protection.html](https://eur-lex.europa.eu/EN/legal-content/summary/copyright-and-related-rights-term-of-protection.html)

## Acknowledgments

The author would like to thank Vladimir Viro and Dmitrii Gavrilev for their feedback and suggestions regarding early versions of the alignment refinement algorithm and the dataset. The author is grateful to the TISMIR editorial team and the anonymous reviewers for their constructive and invaluable feedback, which improved the quality of the dataset and manuscript.

The work was made possible by the use of the Zhores cluster and its computational resources (**[Zacharov et al., 2019](#r49)**). Furthermore, the author expresses gratitude to the creators of the MAESTRO, ASAP, (n)ASAP, ATEPP, GiantMIDI‑Piano, Aria‑MIDI, and PERiScoPe datasets. Their commitment to open science and the sharing of symbolic music resources provided the essential foundation for this work.

## Ethical Statement

The curation of large‑scale symbolic datasets presents challenges regarding copyright and intellectual property. A best‑effort attempt was made to filter PianoCoRe according to European Union public‑domain regulations (works whose authors have been deceased for more than 70 years). However, achieving 100% accuracy across thousands of files from diverse sources is inherently difficult. For transparency, the annotated composer metadata is released alongside the dataset.

The dataset, original and processed files, metadata, and alignment annotations are published under a CC‑BY‑NC‑SA 4.0 license. The license respects the licenses used for the source datasets. No formal ethics approval or human participant consent was required for this study, as it involved the processing of publicly available MIDI data and did not involve human subjects.

## Data Accessibility

The PianoCoRe dataset and related resources are released to enforce reproducibility:

- **Code:** The source code, documentation, and usage examples are available at the project repository: [https://github.com/ilya16/PianoCoRe](https://github.com/ilya16/PianoCoRe);
- **Dataset:** The data are archived on Zenodo at [https://doi.org/10.5281/zenodo.19186016](https://doi.org/10.5281/zenodo.19186016) and is available on Hugging Face at [https://huggingface.co/ datasets/SyMuPe/PianoCoRe](https://huggingface.co/%20datasets/SyMuPe/PianoCoRe).

## Competing Interests

The author has no competing interests to declare.

## Author’s Contribution

Ilya Borovik was responsible for the research conceptualization, methodology, software implementation, data curation, and the writing of the manuscript.

## References

- Benetos, E., Dixon, S., Duan, Z., and Ewert, S. (2018). Automatic music transcription: An overview. *IEEE Signal Processing Magazine*, 36(1), 20–30.
- Borovik, I., Gavrilev, D., and Viro, V. (2025). SyMuPe: Affective and controllable symbolic music performance. In Proceedings of the 33rd ACM International Conference on Multimedia, Dublin, Ireland, pp. 10699–10708.
- Borovik, I., and Viro, V. (2023). ScorePerformer: Expressive piano performance rendering with fine‑grained control. In Proceedings of the 24th International Society for Music Information Retrieval Conference (ISMIR), Milan, Italy, pp. 588–596.
- Bradshaw, L., and Colton, S. (2025). Aria‑MIDI: A dataset of piano MIDI files for symbolic music modeling. In Proceedings of the 13th International Conference on Representation Learning (ICLR), Singapore, Singapore.
- Bradshaw, L., Fan, H., Spangher, A., Biderman, S., and Colton, S. (2025). Scaling self‑supervised representation learning for symbolic piano performance. In Proceedings of the 26th International Society for Music Information Retrieval Conference (ISMIR), Daejeon, Korea, pp. 451–459.
- Cancino‑Chacón, C. E., Grachten, M., Goebl, W., and Widmer, G. (2018). Computational models of expressive music performance: A comprehensive and critical review. *Frontiers in Digital Humanities*, 5, 25.
- Cancino‑Chacón, C. E., Peter, S. D., Karystinaios, E., Foscarin, F., Grachten, M., and Widmer, G. (2022). Partitura: A Python package for symbolic music processing. In Proceedings of the Music Encoding Conference (MEC), Halifax, Canada.
- Chou, Y.‑H., Chen, I.‑C., Ching, J., Chang, C.‑J., and Yang, Y.‑H. (2024). MidiBERT‑Piano: Large‑scale pre‑training for symbolic music classification tasks. *Journal of Creative Music Systems*, 8(1).
- Edwards, D., Dixon, S., and Benetos, E. (2023). PiJAMA: Piano jazz with automatic MIDI annotations. *Transactions of the International Society for Music Information Retrieval*, 6(1), 89–102.
- Edwards, D., Dixon, S., Benetos, E., Maezawa, A., and Kusaka, Y. (2024). A data‑driven analysis of robust automatic piano transcription. *IEEE Signal Processing Letters*, 31, 681–685.
- Emerson, K., and Harrison, P. M. C. (2025). Multimodal datasets for studying expert performances of musical scores. *Transactions of the International Society for Music Information Retrieval*, 8(1), 400–428.
- Foscarin, F., Mcleod, A., Rigaux, P., Jacquemard, F., and Sakai, M. (2020). *ASAP: A dataset of aligned scores and performances for piano transcription*. In Proceedings of the 21st International Society for Music Information Retrieval Conference (ISMIR), Montréal, Canada, pp. 534–541.
- Goebl, W. (1999). *The Vienna 4x22 Piano Corpus*. [https://doi.org/10.21939/4X22](https://doi.org/10.21939/4X22).
- Good, M. (2001). MusicXML for notation and analysis. In *The Virtual Score: Representation, Retrieval, Restoration*, 12, 113–124.
- Guo, Z., Kang, J., and Herremans, D. (2023). A domain‑ knowledge‑inspired music embedding space and a novel attention mechanism for symbolic music modeling. In Proceedings of the 37th AAAI Conference on Artificial Intelligence, Volume 37, Washington, DC, USA, pp. 5070–5077.
- Hashida, M., Nakamura, E., and Katayose, H. (2018). Crest‑ MusePEDB 2nd edition: Music performance database with phrase information. In Proceedings of the 15th Sound and Music Computing Conference (SMC), Limassol, Cyprus.
- Hawthorne, C., Stasyuk, A., Roberts, A., Simon, I., Huang, C.‑Z. A., Dieleman, S., Elsen, E., Engel, J., and Eck, D. (2019). Enabling factorized piano music modeling and generation with the MAESTRO dataset. In Proceedings of the 7th International Conference on Representation Learning (ICLR), New Orleans, LA, USA.
- Hsiao, W.‑Y., Liu, J.‑Y., Yeh, Y.‑C., and Yang, Y.‑H. (2021). Compound word transformer: Learning to compose full‑song music over dynamic directed hypergraphs. In Proceedings of the 35th AAAI Conference on Artificial Intelligence (Volume 35, pp. 178–186). Virtual Event.
- Hu, P., Marták, L. S., Cancino‑Chacón, C., and Widmer, G. (2024). Towards musically informed evaluation of piano transcription models. In Proceedings of the 25th International Society for Music Information Retrieval Conference (ISMIR), San Francisco, CA, USA, pp. 1068–1075.
- Hu, P., and Widmer, G. (2023). The Batik‑Plays‑Mozart corpus: Linking performance to score to musicological annotations. In Proceedings of the 24th International Society for Music Information Retrieval Conference (ISMIR), Milan, Italy, pp. 297–303.
- Huang, Y.‑S., and Yang, Y.‑H. (2020). Pop music transformer: Beat‑based modeling and generation of expressive pop piano compositions. In Proceedings of the 28th ACM International Conference on Multimedia, Virtual Event and Seattle, WA, USA, pp. 1180–1188.
- Hung, H.‑T., Ching, J., Doh, S., Kim, N., Nam, J., and Yang, Y.‑H. (2021). EMOPIA: A multi‑modal pop piano dataset for emotion recognition and emotion‑based music generation. In Proceedings of the 22nd International Society for Music Information Retrieval Conference (ISMIR), pp. 318–325. Online.
- Jeong, D., Kwon, T., Kim, Y., Lee, K., and Nam, J. (2019a). VirtuosoNet: A hierarchical RNN‑based system for modeling expressive piano performance. In Proceedings of the 20th International Society for Music Information Retrieval Conference (ISMIR), Delft, Netherlands, pp. 908–915.
- Jeong, D., Kwon, T., Kim, Y., and Nam, J. (2019b). Graph neural network for music score data and modeling expressive piano performance. In Proceedings of the 36th International Conference on Machine Learning (ICML), Long Beach, CA, USA, pp. 3060–3070. PMLR.
- Kong, Q., Li, B., Chen, J., and Wang, Y. (2022). GiantMIDI‑Piano: A large‑scale MIDI dataset for classical piano music. *Transactions of the International Society for Music Information Retrieval*, Bengaluru, India, 5(1), 87–98.
- Kong, Q., Li, B., Song, X., Wan, Y., and Wang, Y. (2021). High‑resolution piano transcription with pedals by regressing onset and offset times. *IEEE/ACM Transactions on Audio, Speech, and Language Processing*, 29, 3707–3717.
- Kosta, K., Bandtlow, O. F., and Chew, E. (2018). MazurkaBL: Score‑aligned loudness, beat, expressive markings data for 2000 Chopin Mazurka recordings. In Proceedings of the 4th International Conference on Technologies for Music Notation and Representation (TENOR), Montréal, Canada, pp. 85–94.
- Lam, S. K., Pitrou, A., and Seibert, S. (2015). Numba: A LLVM‑based Python JIT compiler. In Proceedings of the Second Workshop on the LLVM Compiler Infrastructure in HPC, Austin, TX, USA, pp. 1–6.
- Lee, K. J. M., Ens, J., Adkins, S., Sarmento, P., Barthet, M., and Pasquier, P. (2025). The GigaMIDI dataset with features for expressive music performance detection. *Transactions of the International Society for Music Information Retrieval*, 8(1), 1–19.
- Lerch, A., Arthur, C., Pati, A., and Gururani, S. (2020). An interdisciplinary review of music performance analysis. *Transactions of the International Society for Music Information Retrieval*, 3(1), 221–245.
- Liang, X., Zhao, Z., Zeng, W., He, Y., He, F., Wang, Y., and Gao, C. (2024). PianoBART: Symbolic piano music generation and understanding with large‑scale pre‑training. In Proceedings of the 25th IEEE International Conference on Multimedia and Expo (ICME), IEEE, Niagara Falls, ON, Canada, pp. 1–6.
- Liao, Y., Luo, Z., Wang, Y., and Yin, Y. (2024). Symusic: A swift and unified toolkit for symbolic music processing. In Extended Abstracts of the 25th International Society for Music Information Retrieval Conference (ISMIR), San Francisco, CA, USA.
- Lipman, Y., Chen, R. T., Ben‑Hamu, H., Nickel, M., and Le, M. (2022). Flow matching for generative modeling. In The Proceedings of the 11th International Conference on Learning Representations (ICLR), Virtual Event.
- Long, P., Novack, Z., Berg‑Kirkpatrick, T., and McAuley, J. (2025). PDMX: A large‑scale public domain MusicXML dataset for symbolic music processing. In Proceedings of the 50th IEEE International Conference on Acoustics, Speech and Signal Processing (ICASSP), IEEE, Hyderabad, India, pp. 1–5.
- Müller, M., Konz, V., Bogler, W., and Arifi‑Müller, V. (2011). Saarland Music Data (SMD). In Extended Abstracts for the Late‑Breaking Demo Session of the 12th International Society for Music Information Retrieval Conference (ISMIR), Miami, FL, USA.
- Nakamura, E., Yoshii, K., and Katayose, H. (2017). Performance error detection and post‑processing for fast and accurate symbolic music alignment. In Proceedings of the 18th International Society for Music Information Retrieval Conference (ISMIR), Suzhou, China, pp. 347–353.
- Peter, S. D. (2023). Online symbolic music alignment with offline reinforcement learning. In Proceedings of the 24th International Society for Music Information Retrieval Conference (ISMIR), Milan, Italy, pp. 634–641.
- Peter, S. D., Cancino‑Chacón, C. E., Foscarin, F., McLeod, A. P., Henkel, F., Karystinaios, E., and Widmer, G. (2023). Automatic note‑level score‑to‑performance alignments in the ASAP dataset. *Transactions of the International Society for Music Information Retrieval*, 6(1), 27–42.
- Rhyu, S., Kim, S., and Lee, K. (2022). Sketching the expression: Flexible rendering of expressive piano performance with self‑supervised learning. In Proceedings of the 23rd International Society for Music Information Retrieval Conference (ISMIR), Bengaluru, India, pp.178–185.
- Shi, Z., Sapp, C., Arul, K., McBride, J., and Smith III, J. O. (2019). SUPRA: Digitizing the Stanford University Piano Roll Archive. In Proceedings of the 20th International Society for Music Information Retrieval Conference (ISMIR), Delft, Netherlands, pp. 517–523.
- Simonetta, F., Avanzini, F., and Ntalampiras, S. (2022). A perceptual measure for evaluating the resynthesis of automatic music transcriptions. *Multimedia Tools and Applications*, 81(22), 32371–32391.
- Su, J., Ahmed, M., Lu, Y., Pan, S., Bo, W., and Liu, Y. (2024). RoFormer: Enhanced Transformer with rotary position embedding. *Neurocomputing*, 568, 127063.
- Tang, J., Cooper, E., Wang, X., Yamagishi, J., and Fazekas, G. (2025). Towards an integrated approach for expressive piano performance synthesis from music scores. In Proceedings of the 50th IEEE International Conference on Acoustics, Speech and Signal Processing (ICASSP), Hyderabad, India, pp. 1–5.
- Vaswani, A., Shazeer, N., Parmar, N., Uszkoreit, J., Jones, L., Gomez, A. N., Kaiser, L., and Polosukhin, I. (2017). Attention is all you need. In *Advances in Neural Information Processing Systems (NIPS)* (Volume 30, pp. 5998–6008). Curran Associates, Inc.
- Watson, M. (2018). MuseScore. *Journal of the Musical Arts in Africa*, 15(1–2), 143–147.
- Xia, G. G. (2016). *Expressive Collaborative Music Performance via Machine Learning \[PhD thesis\]*. Carnegie Mellon University.
- Yan, Y., and Duan, Z. (2024). Scoring time intervals using non‑hierarchical Transformer for automatic piano transcription. In Proceedings of the 25th International Society for Music Information Retrieval Conference (ISMIR), San Francisco, CA, USA, pp. 973–980.
- Ycart, A., Liu, L., Benetos, E., and Pearce, M. (2020). Investigating the perceptual validity of evaluation metrics for automatic piano music transcription. *Transactions of the International Society for Music Information Retrieval*, 3(1), 68–81.
- Zacharov, I., Arslanov, R., Gunin, M., Stefonishin, D., Bykov, A., Pavlov, S., Panarin, O., Maliutin, A., Rykovanov, S., and Fedorov, M. (2019). “Zhores”: Petaflops supercomputer for data‑driven modeling, machine learning and artificial intelligence installed in Skolkovo Institute of Science and Technology. *Open Engineering*, 9(1), 512–520.
- Zeng, M., Tan, X., Wang, R., Ju, Z., Qin, T., and Liu, T.‑Y. (2021). MusicBERT: Symbolic music understanding with large‑scale pre‑training. In *Findings of the Association for Computational Linguistics: ACL‑IJCNLP 2021*, pp. 791–800.
- Zhang, H., Chowdhury, S., Cancino‑Chacón, C. E., Liang, J., Dixon, S., and Widmer, G. (2024). DExter: Learning and controlling performance expression with diffusion models. *Applied Sciences*, 14(15), 6543.
- Zhang, H., Tang, J., Rafee, S. R. M., and Fazekas, S. D. G. (2022). ATEPP: A dataset of automatically transcribed expressive piano performance. In Proceedings of the 23rd International Society for Music Information Retrieval Conference (ISMIR), Bengaluru, India, pp. 446–453.

[^1]: ## 8 Conclusion

This article presented **PianoCoRe**, a unified, large‑scale piano MIDI dataset created by combining, refining, annotating, and aligning existing open‑source corpora. Released in tiered subsets, PianoCoRe supports a wide spectrum of tasks: from performance analysis and large‑scale pre‑training to expressive piano performance rendering and score‑to‑performance translation. The dataset enables reproducible research by allowing researchers to create non‑overlapping data splits across previously isolated datasets.

To ensure data integrity, two challenges were addressed: the quality of performance MIDI and note‑level alignments. A classifier was trained to identify deadpan and corrupted MIDI transcriptions, and an alignment refinement pipeline was designed to remove temporal outliers in aligned score‑performance data. The experiments showed that the model trained on these refined subsets benefits from the increased repertoire diversity and cleaner note features.

Future directions include extending the methodology to multi‑instrument repertoires, developing more robust quality assessment models and incorporating more granular score and performance annotations. By making PianoCoRe openly available, the goal is to establish a foundation for advancing symbolic music performance modeling and analysis research.

[^2]: [https://github.com/ilya16/PianoCoRe](https://github.com/ilya16/PianoCoRe)

[^3]: [https://doi.org/10.5281/zenodo.19186016](https://doi.org/10.5281/zenodo.19186016)

[^4]: [https://huggingface.co/datasets/SyMuPe/PianoCoRe](https://huggingface.co/datasets/SyMuPe/PianoCoRe)

[^5]: [https://github.com/CPJKU/asap-dataset](https://github.com/CPJKU/asap-dataset)

[^6]: [https://github.com/tangjjbetsy/ATEPP](https://github.com/tangjjbetsy/ATEPP)

[^7]: [https://github.com/bytedance/GiantMIDI-Piano](https://github.com/bytedance/GiantMIDI-Piano)

[^8]: [https://huggingface.co/datasets/SyMuPe/PERiScoPe](https://huggingface.co/datasets/SyMuPe/PERiScoPe)

[^9]: [https://huggingface.co/datasets/loubb/aria-midi](https://huggingface.co/datasets/loubb/aria-midi)

[^10]: [https://musescore.com/sheetmusic](https://musescore.com/sheetmusic)

[^11]: [https://kunstderfuge.com](https://kunstderfuge.com/)

[^12]: [https://www.classicalmidi.co.uk](https://www.classicalmidi.co.uk/)

[^13]: [https://imslp.org](https://imslp.org/)

[^14]: [https://eur-lex.europa.eu/EN/legal-content/summary/copyright-and-related-rights-term-of-protection.html](https://eur-lex.europa.eu/EN/legal-content/summary/copyright-and-related-rights-term-of-protection.html)