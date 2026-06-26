import pandas as pd

def attach_housing(nights_df: pd.DataFrame, housing_df: pd.DataFrame,
                   logger_col: str = "logger_id") -> pd.DataFrame:
    return nights_df.merge(housing_df, on=logger_col, how="left")
