import numpy as np
from scipy.linalg import null_space

class TrussStructure:
    def __init__(self, nodes, elements, E=1.0, A=1.0):
        """
        初始化桁架结构
        
        参数:
        nodes: 节点列表，格式为 [节点编号, x坐标, y坐标, z坐标]
        elements: 单元列表，格式为 [单元编号, 起始节点, 结束节点]
        E: 弹性模量 (默认1.0)
        A: 截面积 (默认1.0)
        """
        self.nodes = np.array(nodes)
        self.elements = np.array(elements)
        self.E = E
        self.A = A
        self.n_nodes = len(nodes)
        self.n_elements = len(elements)
        self.n_dof = 3 * self.n_nodes  # 每个节点有3个自由度
        
        # 创建节点编号到索引的映射
        self.node_id_to_index = {}
        for i, node in enumerate(self.nodes):
            self.node_id_to_index[node[0]] = i
    
    def assemble_global_stiffness(self):
        """组装全局刚度矩阵"""
        K_global = np.zeros((self.n_dof, self.n_dof))
        
        for element in self.elements:
            elem_id, start_node_id, end_node_id = element[:3]  # 只取前三个元素
            
            start_node_idx = self.node_id_to_index[start_node_id]
            end_node_idx = self.node_id_to_index[end_node_id]
            
            # 获取节点坐标
            start_node = self.nodes[start_node_idx][1:]
            end_node = self.nodes[end_node_idx][1:]
            
            # 计算单元长度和方向余弦
            dx = end_node - start_node
            L = np.linalg.norm(dx)
            cos = dx / L
            
            # 计算单元刚度矩阵 (在局部坐标系中)
            k_local = (self.E * self.A / L) * np.array([
                [1, -1],
                [-1, 1]
            ])
            
            # 转换矩阵 (从局部到全局)
            T = np.zeros((6, 2))
            T[0:3, 0] = cos
            T[3:6, 1] = cos
            
            # 全局坐标系中的单元刚度矩阵
            k_global_elem = T @ k_local @ T.T
            
            # 组装到全局刚度矩阵
            start_dof = 3 * start_node_idx
            end_dof = 3 * end_node_idx
            
            indices = np.concatenate([np.arange(start_dof, start_dof+3), 
                                     np.arange(end_dof, end_dof+3)])
            
            for i, idx_i in enumerate(indices):
                for j, idx_j in enumerate(indices):
                    K_global[idx_i, idx_j] += k_global_elem[i, j]
        
        return K_global
    
    def apply_boundary_conditions(self, K_global, constrained_nodes, constrained_dofs):
        """
        应用边界条件
        
        参数:
        K_global: 全局刚度矩阵
        constrained_nodes: 受约束的节点列表
        constrained_dofs: 每个节点受约束的自由度 (0=x, 1=y, 2=z)
        """
        constrained_dof_indices = []
        
        for node_id in constrained_nodes:
            if node_id in self.node_id_to_index:
                node_idx = self.node_id_to_index[node_id]
                for dof in constrained_dofs:
                    dof_idx = 3 * node_idx + dof
                    constrained_dof_indices.append(dof_idx)
        
        # 对约束自由度进行处理 (置1法)
        for dof in constrained_dof_indices:
            K_global[dof, :] = 0
            K_global[:, dof] = 0
            K_global[dof, dof] = 1
        
        return K_global, constrained_dof_indices
    
    def check_singularity(self, constrained_nodes, constrained_dofs=[2]):
        """
        检查刚度矩阵是否奇异
        
        参数:
        constrained_nodes: 受约束的节点列表
        constrained_dofs: 每个节点受约束的自由度 (默认只约束z方向)
        """
        # 组装全局刚度矩阵
        K_global = self.assemble_global_stiffness()
        
        # 应用边界条件
        K_constrained, constrained_dofs = self.apply_boundary_conditions(
            K_global, constrained_nodes, constrained_dofs)
        
        # 检查矩阵是否奇异
        rank = np.linalg.matrix_rank(K_constrained)
        is_singular = rank < K_constrained.shape[0]
        
        if is_singular:
            print("刚度矩阵是奇异的!")
            
            # 计算零空间向量以识别问题节点
            try:
                null_vec = null_space(K_constrained)
                
                if null_vec.size > 0:
                    # 找出位移最大的节点
                    max_displacement = 0
                    problem_node_idx = -1
                    
                    for i in range(self.n_nodes):
                        # 跳过约束节点
                        node_id = self.nodes[i][0]
                        if node_id in constrained_nodes:
                            continue
                        
                        # 计算节点的位移大小
                        dof_start = 3 * i
                        displacement = np.linalg.norm(null_vec[dof_start:dof_start+3])
                        
                        if displacement > max_displacement:
                            max_displacement = displacement
                            problem_node_idx = i
                    
                    if problem_node_idx != -1:
                        problem_node_id = self.nodes[problem_node_idx][0]
                        print(f"问题可能出现在节点 {problem_node_id} (索引 {problem_node_idx})")
                        print(f"该节点的位移向量: {null_vec[3*problem_node_idx:3*problem_node_idx+3].flatten()}")
                else:
                    print("无法确定具体问题节点")
            except:
                print("计算零空间时出错，可能矩阵过于奇异")
        else:
            print("刚度矩阵是非奇异的，结构是稳定的。")
        
        return is_singular, K_constrained

def read_nodes_file(filename):
    """读取节点文件"""
    nodes = []
    with open(filename, 'r') as f:
        for line in f:
            if line.startswith('node'):
                parts = line.split()
                node_id = int(parts[1])
                x = float(parts[2])
                y = float(parts[3])
                z = float(parts[4])
                nodes.append([node_id, x, y, z])
    return nodes

def read_elements_file(filename):
    """读取单元文件"""
    elements = []
    with open(filename, 'r') as f:
        for line in f:
            if line.startswith('element trussSection'):
                parts = line.split()
                elem_id = int(parts[2])
                start_node = int(parts[3])
                end_node = int(parts[4])
                elements.append([elem_id, start_node, end_node])
    return elements

# 主程序
if __name__ == "__main__":
    # 读取节点和单元数据
    nodes = read_nodes_file('Src/Node.tcl')  # 替换为您的节点文件名
    elements = read_elements_file('Src/Element.tcl')  # 替换为您的单元文件名
    
    print(f"读取了 {len(nodes)} 个节点")
    print(f"读取了 {len(elements)} 个单元")
    import numpy as np
from scipy.linalg import null_space

class TrussStructure:
    def __init__(self, nodes, elements, E=1.0, A=1.0):
        """
        初始化桁架结构
        
        参数:
        nodes: 节点列表，格式为 [节点编号, x坐标, y坐标, z坐标]
        elements: 单元列表，格式为 [单元编号, 起始节点, 结束节点]
        E: 弹性模量 (默认1.0)
        A: 截面积 (默认1.0)
        """
        self.nodes = np.array(nodes)
        self.elements = np.array(elements)
        self.E = E
        self.A = A
        self.n_nodes = len(nodes)
        self.n_elements = len(elements)
        self.n_dof = 3 * self.n_nodes  # 每个节点有3个自由度
        
        # 创建节点编号到索引的映射
        self.node_id_to_index = {}
        for i, node in enumerate(self.nodes):
            self.node_id_to_index[node[0]] = i
    
    def assemble_global_stiffness(self):
        """组装全局刚度矩阵"""
        K_global = np.zeros((self.n_dof, self.n_dof))
        
        for element in self.elements:
            elem_id, start_node_id, end_node_id = element[:3]  # 只取前三个元素
            
            start_node_idx = self.node_id_to_index[start_node_id]
            end_node_idx = self.node_id_to_index[end_node_id]
            
            # 获取节点坐标
            start_node = self.nodes[start_node_idx][1:]
            end_node = self.nodes[end_node_idx][1:]
            
            # 计算单元长度和方向余弦
            dx = end_node - start_node
            L = np.linalg.norm(dx)
            cos = dx / L
            
            # 计算单元刚度矩阵 (在局部坐标系中)
            k_local = (self.E * self.A / L) * np.array([
                [1, -1],
                [-1, 1]
            ])
            
            # 转换矩阵 (从局部到全局)
            T = np.zeros((6, 2))
            T[0:3, 0] = cos
            T[3:6, 1] = cos
            
            # 全局坐标系中的单元刚度矩阵
            k_global_elem = T @ k_local @ T.T
            
            # 组装到全局刚度矩阵
            start_dof = 3 * start_node_idx
            end_dof = 3 * end_node_idx
            
            indices = np.concatenate([np.arange(start_dof, start_dof+3), 
                                     np.arange(end_dof, end_dof+3)])
            
            for i, idx_i in enumerate(indices):
                for j, idx_j in enumerate(indices):
                    K_global[idx_i, idx_j] += k_global_elem[i, j]
        
        return K_global
    
    def apply_boundary_conditions(self, K_global, constrained_nodes, constrained_dofs):
        """
        应用边界条件
        
        参数:
        K_global: 全局刚度矩阵
        constrained_nodes: 受约束的节点列表
        constrained_dofs: 每个节点受约束的自由度 (0=x, 1=y, 2=z)
        """
        constrained_dof_indices = []
        
        for node_id in constrained_nodes:
            if node_id in self.node_id_to_index:
                node_idx = self.node_id_to_index[node_id]
                for dof in constrained_dofs:
                    dof_idx = 3 * node_idx + dof
                    constrained_dof_indices.append(dof_idx)
        
        # 对约束自由度进行处理 (置1法)
        for dof in constrained_dof_indices:
            K_global[dof, :] = 0
            K_global[:, dof] = 0
            K_global[dof, dof] = 1
        
        return K_global, constrained_dof_indices
    
    def check_singularity(self, constrained_nodes, constrained_dofs=[0, 1, 2]):
        """
        检查刚度矩阵是否奇异
        
        参数:
        constrained_nodes: 受约束的节点列表
        constrained_dofs: 每个节点受约束的自由度 (默认约束x,y,z三个方向)
        """
        # 组装全局刚度矩阵
        K_global = self.assemble_global_stiffness()
        
        # 应用边界条件
        K_constrained, constrained_dofs = self.apply_boundary_conditions(
            K_global, constrained_nodes, constrained_dofs)
        
        # 检查矩阵是否奇异
        rank = np.linalg.matrix_rank(K_constrained)
        is_singular = rank < K_constrained.shape[0]
        
        if is_singular:
            print("刚度矩阵是奇异的!")
            
            # 计算零空间向量以识别问题节点
            try:
                null_vec = null_space(K_constrained)
                
                if null_vec.size > 0:
                    # 找出位移最大的节点
                    max_displacement = 0
                    problem_nodes = []
                    
                    for i in range(self.n_nodes):
                        # 跳过约束节点
                        node_id = self.nodes[i][0]
                        if node_id in constrained_nodes:
                            continue
                        
                        # 计算节点的位移大小
                        dof_start = 3 * i
                        displacement = np.linalg.norm(null_vec[dof_start:dof_start+3])
                        
                        # 记录所有非零位移节点
                        if displacement > 1e-6:  # 设置一个小阈值
                            problem_nodes.append((node_id, displacement))
                    
                    if problem_nodes:
                        # 按位移大小排序
                        problem_nodes.sort(key=lambda x: x[1], reverse=True)
                        print("可能存在问题的节点 (按位移大小排序):")
                        for node_id, displacement in problem_nodes:
                            print(f"节点 {node_id}: 位移大小 = {displacement:.6e}")
                    else:
                        print("所有非约束节点的位移都很小，问题可能在于约束不足或单元连接问题")
                else:
                    print("无法确定具体问题节点")
            except Exception as e:
                print(f"计算零空间时出错: {e}")
        else:
            print("刚度矩阵是非奇异的，结构是稳定的。")
        
        return is_singular, K_constrained

def read_nodes_file(filename):
    """读取节点文件"""
    nodes = []
    with open(filename, 'r') as f:
        for line in f:
            if line.startswith('node'):
                parts = line.split()
                node_id = int(parts[1])
                x = float(parts[2])
                y = float(parts[3])
                z = float(parts[4])
                nodes.append([node_id, x, y, z])
    return nodes

def read_elements_file(filename):
    """读取单元文件"""
    elements = []
    with open(filename, 'r') as f:
        for line in f:
            if line.startswith('element trussSection'):
                parts = line.split()
                elem_id = int(parts[2])
                start_node = int(parts[3])
                end_node = int(parts[4])
                elements.append([elem_id, start_node, end_node])
    return elements

# 主程序
if __name__ == "__main__":
    # 读取节点和单元数据
    nodes = read_nodes_file('Src/Node.tcl')  # 替换为您的节点文件名
    elements = read_elements_file('Src/Element.tcl')  # 替换为您的单元文件名
    
    print(f"读取了 {len(nodes)} 个节点")
    print(f"读取了 {len(elements)} 个单元")
    
    # 创建桁架结构
    truss = TrussStructure(nodes, elements)
    
    # 定义约束节点 (四个底部节点的x,y,z三个方向固定)
    constrained_nodes = [2430, 2431, 2432, 2433]  # 节点编号
    
    # 检查奇异性
    is_singular, K = truss.check_singularity(constrained_nodes, constrained_dofs=[0, 1, 2])
    
    # 可选: 查看刚度矩阵
    # print("约束后的刚度矩阵:")
    # print(K)
