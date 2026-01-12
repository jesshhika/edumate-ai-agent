import google.generativeai as genai

genai.configure(api_key="AIzaSyAuzgklw0I5Du8qFOt37YLJ-h5ocwzpdhc")

models = list(genai.list_models())  # convert generator to list
print(models)
