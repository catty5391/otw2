class SearchKeyword:
    def __init__(self, path, keyword):
        self.path = path
        self.keyword = keyword

    def search(self):
        with open(self.path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        for index, line in enumerate(lines):
            if self.keyword in line:
                return index + 1, lines

        return -1, lines