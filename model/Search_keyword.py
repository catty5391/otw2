#此方法用来检索特定文件中，具体关键词所在行号，返回(行号+1)作为结果

class Search_keyword():
    def __init__(self, path, keyword):
        self.path = path
        self.keyword = keyword

    def Search(self):
        with open(self.path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            for index, line in enumerate(lines):
                if self.keyword in line:
                    start_line = index + 1
                    break
            else:
                start_line = -1

        return start_line, lines