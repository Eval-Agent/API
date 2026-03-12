# Student Evaluation Data

**Student Name:** [illegible]
**Roll Number:** N/A

## Question ID: 1
**Max Score:** 2

### Question
Mention two ethical concerns in AI.

### Student Answer
Two ethical concerns in AI are:-
(i) Accountability -> If some sort of damage occurs, then who is supposed to be held accountable because the fault is of the AI.
(ii) Privacy -> A whole lot of private data is fetched to an AI, so it is a concern that it is kept private and not leaked.
(iii) Bias -> Acts of racism or bias based on ethnicity shouldn't be done.

### Rubric
**Expected Depth:** definition

#### Concepts
- **Concept:** Ethical Concerns
  - Description: Identify two distinct ethical issues related to AI deployment.
  - Keywords: Bias, Privacy, Accountability, Transparency, Safety
  - Mandatory: True
---

## Question ID: 2
**Max Score:** 2

### Question
Define Artificial Intelligence (AI).

### Student Answer
Artificial Intelligence (AI) is the term which basically means a machine or a model which imitates human intelligence. For example, the model is trained in such a way, that it can understand, respond, analyse and use human features or human-like intelligence to maintain an output. Just like we call human intelligence, the machine's intelligence to mirror human intelligence is called Artificial Intelligence.

### Rubric
**Expected Depth:** definition

#### Concepts
- **Concept:** Definition of AI
  - Description: Definition describing machines or software simulating human intelligence.
  - Keywords: Simulation, Human intelligence, Learning, Reasoning, Self-correction
  - Mandatory: True
---

## Question ID: 3
**Max Score:** 2

### Question
Can BFS be used in Puzzle-solving? Why or why not?

### Student Answer
No, BFS cannot be used in puzzle solving.
This is because BFS does not work in an orderly manner or heuristically, it just goes around from top to bottom and won't give out the required result.

### Rubric
**Expected Depth:** definition

#### Concepts
- **Concept:** BFS Applicability
  - Description: Confirming BFS use and noting its space complexity limitations.
  - Keywords: Yes, Complete, Space complexity, Exponential
  - Mandatory: True
---

## Question ID: 4
**Max Score:** 2

### Question
Discuss the overestimation of heuristic function in A* Searching algorithm.

### Student Answer
In order to estimate the heuristic function in A* Searching Algorithm, we use:-

$h(u) = g(u) + h(u)$
$h(u) = g(u) + f(u)$

If $h(u) > h(u)^*$, in that case we say that we have the optimal result, but if it is the other way around, it is called overestimation of the heuristic function $h(u)$ where $g(u)$ is cost incurred till current point & $f(u)$ is cost to be incurred to reach the goal.
It basically means to overanalyze the estimation of the heuristic. Like if suppose it should be 10, it comes to be 100.

### Rubric
**Expected Depth:** definition

#### Concepts
- **Concept:** Heuristic Overestimation
  - Description: Explain how overestimation breaks admissibility.
  - Keywords: Admissibility, Optimality, Sub-optimal solution, Overestimation
  - Mandatory: True
---

## Question ID: 5
**Max Score:** 2

### Question
Explain the training, validation, and testing in ML models.

### Student Answer
ML (Machine Learning) models go through a set of 3 steps in order to produce results:-
- Training -> Training is the phase where the machine is fetched with data and instructions and trained on them so that they can adjust and process accordingly. For example, if a machine is trained to be helping in the medical field then it should know all the details & data of the particular case in order to analyse & produce results.
- Validation -> Validation of an ML model is, the phase where we make sure or validate that the machine is properly designed by trying on some examples. It is to know that it works well enough to be used in real life.
- Testing -> Testing an ML model is the final stage of the process. The model is basically tested upon data of analysis, new observations are taken into account and a full-on practice session is done to check the proper & accurate working of the model.

### Rubric
**Expected Depth:** short_explanation

#### Concepts
- **Concept:** Data Partitioning
  - Description: Define the roles of the three datasets.
  - Keywords: Training set, Validation set, Test set, Generalization, Hyperparameter
  - Mandatory: True
---

## Question ID: 8
**Max Score:** 5

### Question
How does feature selection improve ML models? Provide an example.

### Student Answer
Feature Selection improves ML models because it removes the unwanted features. It only keeps or selects the features that are required by the model to function properly and deletes or stops all other features. If there is a redundant feature, in that case as well, they help sort it out by keeping the feature that would help in to create the model properly.
For example, if there are features like Height, weight, skin colour and the ML model is designing based on BMI, in that case feature selection would not take up skin colour and just height & weight because they are the features that are needed.

### Rubric
**Expected Depth:** short_explanation

#### Concepts
- **Concept:** Benefits of Feature Selection
  - Description: Explain performance and complexity improvements.
  - Keywords: Dimensionality reduction, Overfitting, Computational efficiency, Noise reduction
  - Mandatory: True
- **Concept:** Example
  - Description: Provide an example of removing irrelevant features.
  - Keywords: Irrelevant variables, Model accuracy
  - Mandatory: True
---

## Question ID: 9
**Max Score:** 5

### Question
In a dataset with highly correlated features, how does PCA helps in feature extraction?

### Student Answer
In a dataset which has highly correlated features, PCA can help in feature extraction by matching up which feature is better and has better scope of things in order to line up the model. PCA checks minutely and analyzes the manner of how things would work out if that feature was to be extracted.

### Rubric
**Expected Depth:** detailed_explanation

#### Concepts
- **Concept:** PCA mechanism
  - Description: Explain how PCA transforms features into orthogonal components.
  - Keywords: Variance, Orthogonal, Eigenvalues, Eigenvectors
  - Mandatory: True
- **Concept:** Handling Correlation
  - Description: Address how PCA mitigates information redundancy.
  - Keywords: Dimensionality reduction, Information retention, Multicollinearity
  - Mandatory: True
---

## Question ID: 10
**Max Score:** 10

### Question
Compare Hill climbing with A* searching in terms of approach, efficiency, and limitations.

### Student Answer
Hill Climbing is the approach or algorithm which takes up the next best option & goes ahead with it. For example, if the point of starting is (36) and it has two branches (45) & (12), then as far as Hill Climbing is concerned the next point or path would be (45). That is how hill climbing works. The process continues until all the ways are less than the current state.
A* searching works on the approach of heuristics, i.e estimate. It goes around the cycle based on heuristics and is very orderly.
It follows the formula: 
$h(u) = g(u) + f(u)$
where $h(u)$ is the heuristical outcome,
$g(u)$ is the cost incurred in the past till the current point.
$f(u)$ is the distance b/w the now-state and the future goal.

- In terms of efficiency, A* searching is more efficient because it follows a proper analysed approach whereas Hill Climbing can because of certain limitations avoid getting the optimal solution.
- In terms of limitations, Hill Climbing has more limitations as compared to A* searching like Plateau (flat situation where no option can be chosen as they are both not optimal), Ridge, Local Maxima (the peak isn't the optimal solution but we are not getting the result and are stuck), etc.
These limitations prevent the efficiency part of Hill Climbing approach.
For A* searching, it has limitations as well like overestimation of the heuristical value, etc. But if we're comparing it is at a better place than Hill Climbing is.

### Rubric
**Expected Depth:** analytical

#### Concepts
- **Concept:** Approach Comparison
  - Description: Contrast greedy local search with systematic global search.
  - Keywords: Local search, Heuristic-informed, Path cost, Optimality
  - Mandatory: True
- **Concept:** Efficiency
  - Description: Evaluate computational complexity.
  - Keywords: Time complexity, Space complexity, Search space
  - Mandatory: True
- **Concept:** Limitations
  - Description: Discuss issues like local maxima vs completeness.
  - Keywords: Local optima, Plateaus, Completeness, Memory usage
  - Mandatory: True
---
