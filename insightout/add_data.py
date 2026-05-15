import pandas as pd
from django.db import transaction
from apps.insightout.models import (
    AdminUnit,
    Cluster,
    CleanVariable,
    Household,
    RawVariable,
    TargetOutcome,
)
from .pipeline_utils import (
    handle_exception,
    django_point,
    upsert_variable_records_dict,
)
from .add_record import (
    upsert_raw_variable,
    upsert_clean_variable,
    upsert_household,
    upsert_individual,
    upsert_cluster,
    upsert_variable_link,
    upsert_predicted_questions_set,
    upsert_predicted_question,
)
from .add_group_of_records import (
    upsert_raw_household_responses_for_household,
    upsert_raw_individual_responses_for_individual,
    upsert_clean_household_responses_for_household,
    upsert_raw_cluster_geo_values_for_cluster,
    upsert_clean_cluster_geo_values_for_cluster,
)


##########################
## Raw/Clean Data Input ##
##########################


def add_cluster_geospatial_data_from_df(
    data_df: pd.DataFrame,
    admin_unit_id_col: str,
    cluster_lat_col: str,
    cluster_lon_col: str,
    cluster_id_col: str = "dhs_id",
    clean: bool = False,
) -> bool:
    """
    Upserts clusters and their geospatial variable values from a DHS dataframe.
    Expects one row per cluster. Clusters are linked to existing AdminUnit records
    via admin_unit_id_col. Pass clean=True to write to CleanVariable/CleanClusterGeoValue
    tables instead of their Raw counterparts.
    """

    # Use correct helper functions depending on whether raw or clean data upload
    if clean:
        upsert_variable = upsert_clean_variable
        upsert_cluster_geo_values = upsert_clean_cluster_geo_values_for_cluster
        var_id_name = "name"
    else:
        upsert_variable = upsert_raw_variable
        upsert_cluster_geo_values = upsert_raw_cluster_geo_values_for_cluster
        var_id_name = "dhs_var_id"

    # Make cache of {var_col_name: Django variable record}:
    var_records = upsert_variable_records_dict(
        all_cols=data_df.columns,
        exclude_cols=(admin_unit_id_col, cluster_id_col, cluster_lat_col, cluster_lon_col),
        upsert_variable=upsert_variable,
        var_id_name=var_id_name,
        level="C",
    )

    # Iterate through cluster rows in the dataframe
    try:
        admin_unit_records = {}

        with transaction.atomic():
            for cluster_row in data_df.itertuples(index=False):
                # Get values to save
                admin_unit_id = getattr(cluster_row, admin_unit_id_col)
                cluster_id = getattr(cluster_row, cluster_id_col)
                lat = getattr(cluster_row, cluster_lat_col)
                lon = getattr(cluster_row, cluster_lon_col)

                # Get/cache admin unit object
                if admin_unit_id not in admin_unit_records:
                    admin_unit_records[admin_unit_id] = AdminUnit.objects.get(
                        dhs_admin_unit_id=admin_unit_id
                    )

                # Save/update cluster object in table
                cluster_record = upsert_cluster(
                    {
                        "dhs_cluster_id": cluster_id,
                        "admin_unit": admin_unit_records[admin_unit_id],
                        "point": django_point((lon, lat)),
                    }
                )

                # Save/update individual data values for the cluster
                cluster_values = [
                    {
                        "variable": var_record,
                        "value": getattr(cluster_row, var_name),
                    }
                    for var_name, var_record in var_records.items()
                ]

                upsert_cluster_geo_values(cluster_values, cluster_record)

    except Exception as e:
        handle_exception(e)
        return False

    return True


def add_hh_data_from_df(
    data_df: pd.DataFrame, cluster_id_col: str, hh_id_col: str, clean: bool = False
) -> bool:
    """
    Upserts households and their survey responses from a DHS dataframe.
    Expects one row per household. Clusters must already exist in the DB.
    Pass clean=True to write to CleanVariable/CleanHouseholdResponse tables
    instead of their Raw counterparts.
    """

    # Set up function based on whether adding raw or clean data
    if clean:
        upsert_variable = upsert_clean_variable
        upsert_hh_data = upsert_clean_household_responses_for_household
        var_id_name = "name"
    else:
        upsert_variable = upsert_raw_variable
        upsert_hh_data = upsert_raw_household_responses_for_household
        var_id_name = "dhs_var_id"

    # Make cache of {var_col_name: Django variable record}:
    var_records = upsert_variable_records_dict(
        all_cols=data_df.columns,
        exclude_cols=(hh_id_col, cluster_id_col),
        upsert_variable=upsert_variable,
        var_id_name=var_id_name,
        level="H",
    )

    # Iterate through household rows in the dataframe
    cluster_records = {}
    total = len(data_df)
    try:
        with transaction.atomic():
            for i, hh_row in enumerate(data_df.itertuples(index=False)):
                if i % 1000 == 0:
                    print(f"Processing household {i}/{total}...")

                # Get IDs
                cluster_id = getattr(hh_row, cluster_id_col)
                hh_id = getattr(hh_row, hh_id_col)

                # Get the household's cluster object (should exist at this point)
                if not cluster_records.get(cluster_id):
                    cluster_records[cluster_id] = Cluster.objects.get(dhs_cluster_id=cluster_id)

                # Update or insert household object
                hh_record = upsert_household(
                    {
                        "dhs_household_id": hh_id,
                        "cluster": cluster_records[cluster_id],
                    }
                )

                # Save/update individual responses for the household
                hh_responses = [
                    {
                        "variable": var_record,
                        "response": getattr(hh_row, var_name),
                    }
                    for var_name, var_record in var_records.items()
                ]

                upsert_hh_data(hh_responses, hh_record)

    except Exception as e:
        handle_exception(e)
        return False

    return True


def add_raw_indiv_data_from_df(
    data_df: pd.DataFrame,
    hh_id_col: str,
    indiv_id_col: str,
) -> bool:
    """
    Upserts individuals and their raw survey responses from a DHS dataframe.
    Expects one row per individual. Households must already exist in the DB.
    """

    # Make cache of {var_col_name: Django variable record}:
    var_records = upsert_variable_records_dict(
        all_cols=data_df.columns,
        exclude_cols=(hh_id_col, indiv_id_col),
        upsert_variable=upsert_raw_variable,
        var_id_name="dhs_var_id",
        level="I",
    )

    # Iterate through individual rows in the dataframe
    hh_records = {}
    for indiv_row in data_df.itertuples(index=False):
        try:
            # Get IDs
            hh_id = getattr(indiv_row, hh_id_col)
            indiv_id = getattr(indiv_row, indiv_id_col)

            # Get the individual's household object (should exist at this point)
            if not hh_records.get(hh_id):
                hh_records[hh_id] = Household.objects.get(dhs_household_id=hh_id)

            # Update or insert individual object
            indiv_record = upsert_individual(
                {
                    "dhs_individual_id": indiv_id,
                    "household": hh_records[hh_id],
                }
            )

            # Save/update individual responses for the individual
            indiv_responses = [
                {
                    "variable": var_record,
                    "response": getattr(indiv_row, var_name),
                }
                for var_name, var_record in var_records.items()
            ]

            upsert_raw_individual_responses_for_individual(indiv_responses, indiv_record)

        except Exception as e:
            handle_exception(e)
            return False

    return True


def add_variable_links(
    data_df: pd.DataFrame,
    raw_var_col: str,
    clean_var_col: str,
) -> bool:
    """
    Upserts VariableLink records mapping raw variables to clean variables.
    raw_var_col values must be dhs_var_ids and clean_var_col values must be
    CleanVariable names. Both variables must already exist in the DB.
    """
    for row in data_df.itertuples(index=False):
        try:
            # Insert/update each link between raw/clean vars
            upsert_variable_link(
                {
                    "raw_variable": RawVariable.objects.get(dhs_var_id=getattr(row, raw_var_col)),
                    "clean_variable": CleanVariable.objects.get(name=getattr(row, clean_var_col)),
                }
            )

        except Exception as e:
            handle_exception(e)
            return False

    return True


def add_clean_var_details(
    data_df: pd.DataFrame,
    name_col: str = "variable_name",
    description_col: str = "description",
    model_use_col: str = "model_use",
) -> bool:
    """
    Updates description and model_use on existing CleanVariable records from a DataFrame.
    Expects one row per variable. Variables must already exist in the DB.
    """
    for variable in data_df.itertuples(index=False):
        try:
            # Update description and model_use on the clean variable
            CleanVariable.objects.filter(name=getattr(variable, name_col)).update(
                description=getattr(variable, description_col),
                model_use=getattr(variable, model_use_col),
            )

        except Exception as e:
            handle_exception(e)
            return False

    return True


########
## ML ##
########


def add_model_outputs(
    data_df: pd.DataFrame,
    model_type_col: str = "model_type",
    admin_unit_col: str = "admin_unit",
    outcome_col: str = "outcome",
    selected_metric_col: str = "selected_metric",
    survey_length_col: str = "survey_length",
    accuracy_col: str = "accuracy",
    recall_col: str = "recall",
    f1_col: str = "f1",
    precision_col: str = "precision",
    question_col: str = "question",
    question_weight_col: str = "question_weight",
) -> bool:
    """
    Upserts PredictedQuestionsSet and PredictedQuestion records from a long-format
    DataFrame (one row per question). admin_unit_col must contain dhs_admin_unit_ids
    and outcome_col must contain TargetOutcome names.
    """
    # Build set-level df by dropping question columns and deduplicating
    question_set_df = data_df[
        [
            model_type_col,
            admin_unit_col,
            outcome_col,
            selected_metric_col,
            survey_length_col,
            accuracy_col,
            precision_col,
            recall_col,
            f1_col,
        ]
    ].drop_duplicates()

    # Upsert predicted questions sets, getting back cache of predicted question
    # set records, where key is tuple of primary keys for the record
    predicted_questions_set_records = helper_upsert_predicted_questions_sets(
        question_set_df,
        model_type_col,
        admin_unit_col,
        outcome_col,
        selected_metric_col,
        survey_length_col,
        accuracy_col,
        precision_col,
        recall_col,
        f1_col,
    )
    if predicted_questions_set_records is None:
        return False

    # Upsert individual predicted questions using the predicted set records cache
    return helper_upsert_predicted_questions(
        data_df,
        predicted_questions_set_records,
        admin_unit_col,
        outcome_col,
        selected_metric_col,
        survey_length_col,
        question_col,
        question_weight_col,
    )


def helper_upsert_predicted_questions_sets(
    question_set_df: pd.DataFrame,
    model_type_col: str,
    admin_unit_col: str,
    outcome_col: str,
    selected_metric_col: str,
    survey_length_col: str,
    accuracy_col: str,
    precision_col: str,
    recall_col: str,
    f1_col: str,
) -> dict | None:
    """
    Upserts PredictedQuestionsSet records from a deduplicated set-level DataFrame.
    Returns a dict mapping (admin_unit_id, outcome_name, selected_metric,
    survey_length) to the upserted PredictedQuestionsSet record, or None if an error occurs.
    """
    admin_unit_records = {}
    target_outcome_records = {}
    predicted_questions_set_records = {}

    try:
        for question_set in question_set_df.itertuples(index=False):
            admin_unit_id = getattr(question_set, admin_unit_col)
            outcome_name = getattr(question_set, outcome_col)

            # Get/cache admin unit and target outcome objects
            if admin_unit_id not in admin_unit_records:
                admin_unit_records[admin_unit_id] = AdminUnit.objects.get(
                    dhs_admin_unit_id=admin_unit_id
                )
            if outcome_name not in target_outcome_records:
                target_outcome_records[outcome_name] = TargetOutcome.objects.get(name=outcome_name)

            # Upsert the predicted questions set and cache by unique lookup fields
            question_set_record = upsert_predicted_questions_set(
                {
                    "model_type": getattr(question_set, model_type_col),
                    "admin_unit": admin_unit_records[admin_unit_id],
                    "target_outcome": target_outcome_records[outcome_name],
                    "selected_metric": getattr(question_set, selected_metric_col),
                    "survey_length": getattr(question_set, survey_length_col),
                    "accuracy": getattr(question_set, accuracy_col),
                    "precision": getattr(question_set, precision_col),
                    "recall": getattr(question_set, recall_col),
                    "f1": getattr(question_set, f1_col),
                }
            )
            predicted_questions_set_records[
                (
                    admin_unit_id,
                    outcome_name,
                    getattr(question_set, selected_metric_col),
                    getattr(question_set, survey_length_col),
                )
            ] = question_set_record

    except Exception as e:
        handle_exception(e)
        return None

    return predicted_questions_set_records


def helper_upsert_predicted_questions(
    data_df: pd.DataFrame,
    predicted_questions_set_records: dict,
    admin_unit_col: str,
    outcome_col: str,
    selected_metric_col: str,
    survey_length_col: str,
    question_col: str,
    question_weight_col: str,
) -> bool:
    """
    Upserts PredictedQuestion records from the full long-format DataFrame,
    using the predicted_questions_set_records cache to look up the parent set.
    """
    clean_variable_records = {}

    try:
        for predicted_question in data_df.itertuples(index=False):
            question_name = getattr(predicted_question, question_col)

            # Get/cache clean variable object
            if question_name not in clean_variable_records:
                clean_variable_records[question_name] = CleanVariable.objects.get(
                    name=question_name
                )

            # Upsert predicted question using the predicted question set from cache
            upsert_predicted_question(
                {
                    "predicted_questions_set": predicted_questions_set_records[
                        (
                            getattr(predicted_question, admin_unit_col),
                            getattr(predicted_question, outcome_col),
                            getattr(predicted_question, selected_metric_col),
                            getattr(predicted_question, survey_length_col),
                        )
                    ],
                    "variable": clean_variable_records[question_name],
                    "weight": getattr(predicted_question, question_weight_col),
                }
            )

    except Exception as e:
        handle_exception(e)
        return False

    return True


def add_binned_variable_links(
    data_df: pd.DataFrame,
    clean_var_col: str,
    binned_clean_var_col: str,
) -> bool:
    """
    Upserts VariableLink records mapping raw variables to binned clean variables.
    clean_var_col contains CleanVariable names and binned_clean_var_col contains
    the corresponding binned CleanVariable names. For each clean var, finds all
    raw vars linked to it, then creates VariableLink records from those raw vars
    to the binned clean var. If multiple raw vars map to a clean var, each gets
    its own link to the binned var.
    """
    # Iterate through every pair of clean/binned clean vars
    for row in data_df.itertuples(index=False):
        try:
            # Get the clean var and binned clean var
            clean_var = CleanVariable.objects.get(name=getattr(row, clean_var_col))
            binned_clean_var = CleanVariable.objects.get(name=getattr(row, binned_clean_var_col))

            # Find all raw vars linked to the clean var
            raw_vars = RawVariable.objects.filter(variablelink__clean_variable=clean_var)

            # For each raw var, create a link to the binned clean var
            for raw_var in raw_vars:
                upsert_variable_link(
                    {
                        "raw_variable": raw_var,
                        "clean_variable": binned_clean_var,
                    }
                )

        except Exception as e:
            handle_exception(e)
            return False

    return True
