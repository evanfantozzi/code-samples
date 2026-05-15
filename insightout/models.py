from django.contrib.gis.db import models


class Country(models.Model):
    name = models.CharField(max_length=100)
    iso_code = models.CharField(max_length=3, unique=True)
    polygon = models.MultiPolygonField(null=True, blank=True)

    def __str__(self):
        return self.name


class AdminUnit(models.Model):
    dhs_admin_unit_id = models.CharField(max_length=14, unique=True)
    name = models.CharField(max_length=200)
    country = models.ForeignKey(Country, on_delete=models.CASCADE)
    polygon = models.MultiPolygonField()

    def __str__(self):
        return self.name


class TargetOutcome(models.Model):
    name = models.CharField(max_length=200)

    def __str__(self):
        return self.name


class RawVariable(models.Model):
    LEVELS = [
        ("H", "Household Level"),
        ("I", "Individual Level"),
        ("C", "Cluster Level"),
        ("S", "Satellite"),
    ]

    dhs_var_id = models.CharField(max_length=200, unique=True)
    level = models.CharField(max_length=1, choices=LEVELS)

    def __str__(self):
        return self.dhs_var_id


class CleanVariable(models.Model):
    LEVELS = [
        ("H", "Household Level"),
        ("I", "Individual Level"),
        ("C", "Cluster Level"),
        ("S", "Satellite"),
    ]

    MODEL_USE = [("M", "Mandatory"), ("P", "Predictor"), ("O", "Outcome")]

    name = models.CharField(max_length=200)
    level = models.CharField(max_length=1, choices=LEVELS)

    # Allow description and model use to start off as blank
    description = models.CharField(max_length=200, null=True, blank=True)
    model_use = models.CharField(
        max_length=1,
        choices=MODEL_USE,
        null=True,
        blank=True,
    )

    def __str__(self):
        return self.name


class VariableLink(models.Model):
    raw_variable = models.ForeignKey(RawVariable, on_delete=models.CASCADE)
    clean_variable = models.ForeignKey(CleanVariable, on_delete=models.CASCADE)

    def __str__(self):
        return str(self.pk)


class Resource(models.Model):
    name = models.CharField(max_length=200)
    info = models.CharField(max_length=200)

    def __str__(self):
        return self.name


class TargetOutcomeResource(models.Model):
    resource = models.ForeignKey(Resource, on_delete=models.CASCADE)
    target_outcome = models.ForeignKey(TargetOutcome, on_delete=models.CASCADE)

    def __str__(self):
        return str(self.pk)


class Cluster(models.Model):
    point = models.PointField()
    admin_unit = models.ForeignKey(AdminUnit, on_delete=models.CASCADE)
    dhs_cluster_id = models.CharField(max_length=14, unique=True)

    def __str__(self):
        return str(self.pk)


class ClusterResource(models.Model):
    cluster = models.ForeignKey(Cluster, on_delete=models.CASCADE)
    resource = models.ForeignKey(Resource, on_delete=models.CASCADE)

    def __str__(self):
        return str(self.pk)


class ClusterPolygon(models.Model):
    polygon = models.MultiPolygonField()
    admin_unit = models.ForeignKey(AdminUnit, on_delete=models.CASCADE)
    cluster = models.ForeignKey(Cluster, on_delete=models.CASCADE)

    def __str__(self):
        return str(self.pk)


class Household(models.Model):
    cluster = models.ForeignKey(Cluster, on_delete=models.CASCADE)
    dhs_household_id = models.CharField(max_length=14, unique=True)

    def __str__(self):
        return str(self.pk)


class Individual(models.Model):
    household = models.ForeignKey(Household, on_delete=models.CASCADE)
    dhs_individual_id = models.CharField(max_length=14, unique=True)

    def __str__(self):
        return str(self.pk)


class RawHouseholdResponse(models.Model):
    household = models.ForeignKey(Household, on_delete=models.CASCADE)
    variable = models.ForeignKey(RawVariable, on_delete=models.CASCADE)
    response = models.TextField()

    def __str__(self):
        return str(self.pk)


class CleanHouseholdResponse(models.Model):
    household = models.ForeignKey(Household, on_delete=models.CASCADE)
    variable = models.ForeignKey(CleanVariable, on_delete=models.CASCADE)
    response = models.TextField()

    def __str__(self):
        return str(self.pk)


class RawIndividualResponse(models.Model):
    individual = models.ForeignKey(Individual, on_delete=models.CASCADE)
    variable = models.ForeignKey(RawVariable, on_delete=models.CASCADE)
    response = models.TextField()

    def __str__(self):
        return str(self.pk)


class RawSatelliteData(models.Model):
    point = models.PointField()
    value = models.FloatField()
    variable = models.ForeignKey(RawVariable, on_delete=models.CASCADE)

    def __str__(self):
        return str(self.pk)


class CleanSatelliteData(models.Model):
    cluster = models.ForeignKey(Cluster, on_delete=models.CASCADE)
    value = models.FloatField()
    variable = models.ForeignKey(CleanVariable, on_delete=models.CASCADE)

    def __str__(self):
        return str(self.pk)


class RawClusterGeoValue(models.Model):
    cluster = models.ForeignKey(Cluster, on_delete=models.CASCADE)
    variable = models.ForeignKey(RawVariable, on_delete=models.CASCADE)
    value = models.FloatField()

    def __str__(self):
        return str(self.pk)


class CleanClusterGeoValue(models.Model):
    cluster = models.ForeignKey(Cluster, on_delete=models.CASCADE)
    variable = models.ForeignKey(CleanVariable, on_delete=models.CASCADE)
    value = models.FloatField()

    def __str__(self):
        return str(self.pk)


class CandidateVariable(models.Model):
    target_outcome = models.ForeignKey(TargetOutcome, on_delete=models.CASCADE)
    variable = models.ForeignKey(CleanVariable, on_delete=models.CASCADE)

    def __str__(self):
        return str(self.pk)


class ClusterOutcome(models.Model):
    cluster = models.ForeignKey(Cluster, on_delete=models.CASCADE)
    target_outcome = models.ForeignKey(TargetOutcome, on_delete=models.CASCADE)
    score = models.FloatField()
    false_positive_rate = models.FloatField()
    false_negative_rate = models.FloatField()

    def __str__(self):
        return str(self.pk)


class PredictedQuestionsSet(models.Model):
    MODEL_TYPE = [
        ("L", "Logistic"),
        ("E", "EBM"),
    ]

    SELECTED_METRIC = [
        ("A", "Accuracy"),
        ("F", "F1"),
        ("R", "Recall"),
        ("P", "Precision"),
    ]

    target_outcome = models.ForeignKey(TargetOutcome, on_delete=models.CASCADE)
    admin_unit = models.ForeignKey(AdminUnit, on_delete=models.CASCADE)
    model_type = models.CharField(max_length=20, choices=MODEL_TYPE)
    selected_metric = models.CharField(max_length=20, choices=SELECTED_METRIC)
    survey_length = models.IntegerField()
    accuracy = models.FloatField()
    recall = models.FloatField()
    precision = models.FloatField()
    f1 = models.FloatField()

    def __str__(self):
        return str(self.pk)


class PredictedQuestion(models.Model):
    predicted_questions_set = models.ForeignKey(PredictedQuestionsSet, on_delete=models.CASCADE)
    variable = models.ForeignKey(CleanVariable, on_delete=models.CASCADE)
    weight = models.FloatField()

    def __str__(self):
        return str(self.pk)
