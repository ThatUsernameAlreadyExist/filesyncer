class PathOperations:
    @staticmethod
    def getPathLastElement(path):
        lastElement = path
        items = PathOperations.splitPath(path)
        if items:
            lastElement = items.pop()
        return lastElement
        
    @staticmethod    
    def splitPath(path):
        items = path.split('\\')
        fixedItems = []
        for i in items:
            if i != '':
                subItems = i.split('/')
                for j in subItems:
                     if j != '':
                        fixedItems.append(j)
        return fixedItems
        
    @staticmethod    
    def comparePath(firstPath, secondPath):
        return PathOperations.splitPath(firstPath) == PathOperations.splitPath(secondPath)
        
    @staticmethod    
    def isSubPath(firstPath, secondPath):
        firstElements = PathOperations.splitPath(firstPath)
        secondElements = PathOperations.splitPath(secondPath)
        subPath = False
        if len(firstElements) < len(secondElements):
            subPath = True
            for index, el in enumerate(firstElements):
                if secondElements[index] != el:
                    subPath = False
                    break;
                    
        return subPath
        
        